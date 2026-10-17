"""One-spec/one-chat operator portal; no controller truth or native dispatch here."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import secrets
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from . import share_gateway as share
from .share_gateway import ShareGateway, _Handler, _ShareError, _canonical, _strict_json
from .share_runtime import _path, _regular
from .chat_directory import directive
from .chat_rsi import instruction
from .protocol import digest

_CHAT = re.compile(r'c_[a-f0-9]{32}\Z')
_NODE = re.compile(r'node_[a-f0-9]{32}\Z')
_HASH = re.compile(r'[a-f0-9]{64}\Z')
_REQUEST = re.compile(r'[A-Za-z0-9_-]{8,100}\Z')
_MISSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
_ROUTES = {'/', *('/api/portal/'+x for x in ('login','logout','state','chat','chat/message','chat/prepare-placement','chat/start','placements','nodes','placement','snapshot','messages','message','report'))}
_PRIVATE = {'token','password','secret','credential_digest','operator_token','session_token','argv','code_hashes','spec','rawspec','raw_spec','bound_spec','native_session','spec_path','source','requests','evaluation_root','directory_request','directory_preparation','prompt','output','raw','raw_events','native_request'}
_CHAT_FIELDS = {'id','title','status','messages','proposal','approval_hash','readiness','checks','error','mission_id','placement_preparation','placement_start','model','rsi_configuration','created_at','updated_at'}


def _clean(value):
    """Project private structural fields at every depth, without trusting redaction."""
    if isinstance(value, dict):
        return {k:_clean(v) for k,v in value.items() if k not in _PRIVATE and not any(s in k.lower() for s in ('secret','credential','password','token'))}
    if isinstance(value, list): return [_clean(v) for v in value]
    return value


@dataclass(frozen=True)
class PortalConfig:
    spec_path: Path
    spec_sha256: str
    adopt_chat_id: str | None
    node_allowlist: tuple[str, ...]
    store: object

    def __post_init__(self):
        object.__setattr__(self,'spec_path',_path(self.spec_path,absolute=True))
        if not isinstance(self.spec_sha256,str) or not _HASH.fullmatch(self.spec_sha256): raise ValueError('spec pin')
        if self.adopt_chat_id is not None and (not isinstance(self.adopt_chat_id,str) or not _CHAT.fullmatch(self.adopt_chat_id)): raise ValueError('chat id')
        if (type(self.node_allowlist) is not tuple or len(self.node_allowlist)>4 or len(set(self.node_allowlist))!=len(self.node_allowlist)
                or any(not isinstance(n,str) or not _NODE.fullmatch(n) for n in self.node_allowlist)): raise ValueError('node allowlist')


class OperatorPortalGateway(ShareGateway):
    def __init__(self,upstream_origin,operator_token,scope_label='portal',*,port=0,allow_messages=True,report_path=None,password_verifier=None,portal: PortalConfig):
        if password_verifier is None or allow_messages is not True or scope_label!='portal': raise ValueError('password portal scope')
        self.portal=portal
        self._mutation_lock=threading.Lock()
        self._store_failed=False
        self._requests={}
        self._receipts={}
        self._uncertain=False
        self._spec()
        binding=portal.store.read()
        if binding.get('status')=='NEW' and portal.adopt_chat_id:
            portal.store.write({'status':'CREATED','chat_id':portal.adopt_chat_id,'adopted':True})
        super().__init__(upstream_origin,operator_token,scope_label,port=port,allow_messages=True,report_path=report_path,password_verifier=password_verifier)
        self.RequestHandlerClass=_PortalHandler

    def _spec(self):
        try:
            raw=_regular(self.portal.spec_path,200000)
            if hashlib.sha256(raw).hexdigest()!=self.portal.spec_sha256: raise _ShareError('SPEC_CHANGED',409)
            value=_strict_json(raw)
            if not isinstance(value,dict) or not isinstance(value.get('source'),str) or not value['source']: raise ValueError('fixed spec source')
            return value
        except (OSError,ValueError):
            # A bounded spec read is not a private-store write failure.
            raise _ShareError('PORTAL_PRESEND_READ_FAILED',409) from None

    def _persist(self,value):
        try:self.portal.store.write(value)
        except Exception:
            self._store_failed=True
            raise _ShareError('PORTAL_STORE_FAILED',503) from None

    def _state(self):
        b=self.portal.store.read()
        proof={'sha256':self.portal.spec_sha256,'status':'PENDING'}
        try:
            self._spec()
            if b.get('status') in {'CREATED','CONTEXT_BOUND'}:
                ident=b.get('chat_id')
                if not isinstance(ident,str) or not _CHAT.fullmatch(ident):raise _ShareError('UPSTREAM_CHAT_INVALID')
                chat=self._upstream('GET','/api/chat?chat_id='+ident)
                if chat.get('id')!=ident or not isinstance(chat.get('messages'),list):raise _ShareError('UPSTREAM_CHAT_INVALID')
                self._guard(chat)
                if chat.get('proposal'):proof['status']='VERIFIED'
        except _ShareError as exc:
            proof['verification_code']=exc.code
        return {'schema':'sisyfus.portal.state.v1','binding':{k:b.get(k) for k in ('status','chat_id','adopted')},'mission_id':b.get('mission_id'),
                'mutation_status':'UNKNOWN' if self._uncertain or self._store_failed or b.get('status')=='UNKNOWN' else 'READY',
                'receipts':[{'request_id':k,'outcome':v} for k,v in list(self._receipts.items())[-16:]],
                'spec':proof,'nodes_allowlisted':len(self.portal.node_allowlist),
                'capabilities':{'chat':True,'planning':True,'start':True,'placement':bool(self.portal.node_allowlist),'controls':False,'inventory':False}}

    def _guard(self,chat):
        b=self.portal.store.read();spec=self._spec()
        expected_source=str(Path(spec['source']).expanduser().resolve())
        if (chat.get('source')!=expected_source or chat.get('spec_path')!=str(self.portal.spec_path)
                or chat.get('rsi_configuration')!=spec.get('rsi')
                or b.get('status')=='CONTEXT_BOUND' and any(chat.get(k)!=b.get(k) for k in ('source','spec_path','rsi_configuration'))):
            raise _ShareError('PORTAL_BINDING_DRIFT',409)
        mid=chat.get('mission_id')
        if mid is not None and (not isinstance(mid,str) or not _MISSION.fullmatch(mid)): raise _ShareError('UPSTREAM_CHAT_INVALID')
        if b.get('mission_id') and mid!=b['mission_id']: raise _ShareError('PORTAL_BINDING_DRIFT',409)
        if chat.get('proposal'):self._verify_adoption(chat,spec)
        return chat

    def _verify_adoption(self,chat,spec):
        # Every ChatSessions._public proposal uses the raw bound spec (not load_lead_spec's
        # normalized result). RSI equality was already checked by _guard.
        expected=digest({'source':chat['source'],'spec':spec,'proposal':chat['proposal']})
        if chat.get('approval_hash')!=expected:raise _ShareError('PORTAL_BINDING_DRIFT',409)

    def _bind(self,chat):
        self._guard(chat)
        b=self.portal.store.read()
        if b.get('adopted') and b.get('status')!='CONTEXT_BOUND' and not chat.get('proposal'):raise _ShareError('PORTAL_ADOPTION_UNVERIFIED',409)
        self._persist({**b,'status':'CONTEXT_BOUND',**{k:copy.deepcopy(chat.get(k)) for k in ('source','spec_path','rsi_configuration','mission_id')}})

    def _chat(self):
        b=self.portal.store.read();ident=b.get('chat_id')
        if not isinstance(ident,str) or not _CHAT.fullmatch(ident):raise _ShareError('PORTAL_CHAT_UNBOUND',409)
        chat=self._upstream('GET','/api/chat?chat_id='+ident)
        if chat.get('id')!=ident or not isinstance(chat.get('messages'),list):raise _ShareError('UPSTREAM_CHAT_INVALID')
        self._guard(chat)
        return chat

    def _projection(self,chat):return _clean({k:v for k,v in chat.items() if k in _CHAT_FIELDS})

    def _mission(self,chat):
        mid=chat.get('mission_id')
        if not isinstance(mid,str) or not _MISSION.fullmatch(mid):raise _ShareError('MISSION_NOT_MAPPED',409)
        return mid

    def _public_placement(self,value):
        if not isinstance(value,dict):raise _ShareError('UPSTREAM_PLACEMENTS_INVALID')
        if value.get('kind')=='local':return {'kind':'local'}
        node=value.get('node_id')
        if value.get('kind')!='remote' or not isinstance(node,str) or not _NODE.fullmatch(node):raise _ShareError('UPSTREAM_PLACEMENTS_INVALID')
        return {'kind':'remote','node_id':node if node in self.portal.node_allowlist else 'UNEXPOSED'}

    def _placements(self,mid):
        value=self._upstream('GET',f'/api/missions/{mid}/placements')
        if not isinstance(value,dict) or value.get('mission_id')!=mid or not isinstance(value.get('placements'),list):raise _ShareError('UPSTREAM_PLACEMENTS_INVALID')
        rows=[]
        for row in value['placements']:
            task=row.get('task_id') if isinstance(row,dict) else None
            if not isinstance(task,str) or not task or len(task.encode())>100:raise _ShareError('UPSTREAM_PLACEMENTS_INVALID')
            rows.append({'task_id':task,'placement':self._public_placement(row.get('placement'))})
        return {'mission_id':mid,'placements':rows}

    def _nodes(self,mid):
        value=self._upstream('GET',f'/api/missions/{mid}/nodes')
        if value.get('mission_id')!=mid or not isinstance(value.get('nodes'),list):raise _ShareError('UPSTREAM_NODES_INVALID')
        nodes=[]
        for n in value['nodes']:
            if not isinstance(n,dict) or not isinstance(n.get('node_id'),str) or not _NODE.fullmatch(n['node_id']):raise _ShareError('UPSTREAM_NODES_INVALID')
            if n['node_id'] in self.portal.node_allowlist:
                if any(not isinstance(n.get(k),str) for k in ('name','status')):raise _ShareError('UPSTREAM_NODES_INVALID')
                nodes.append({k:n[k] for k in ('node_id','name','status')})
        return {'mission_id':mid,'nodes':nodes,'execution_ready':False}

    def _snapshot_for(self,mid):
        # Reuse the exact Share snapshot validation with a local, immutable scope
        # facade; never mutate self.mission_id across HTTP threads.
        scope=SimpleNamespace(mission_id=mid,allow_messages=True,_report=self._report,_upstream=self._upstream)
        capture=ShareGateway._snapshot(scope)
        capture['schema']='sisyfus.portal.capture.v1'
        capture['capture']=_clean(capture['capture'])
        capture['capture_hash']=hashlib.sha256(_canonical(capture['capture'])).hexdigest()
        return capture

    def _create(self,body):
        b=self.portal.store.read();rid=body['request_id']
        if b.get('status')!='NEW':
            if b.get('status')=='CONTEXT_BOUND' and b.get('request_id')==rid:return self._state()
            raise _ShareError('PORTAL_BINDING_UNKNOWN' if b.get('status') in {'UNKNOWN','CREATING','CREATED'} else 'PORTAL_CHAT_ALREADY_BOUND',409)
        self._spec()
        fingerprint=hashlib.sha256(_canonical({'route':'/api/portal/chat','body':body})).hexdigest()
        if rid in self._requests:
            if self._requests[rid]!=fingerprint:raise _ShareError('REQUEST_CONFLICT',409)
            return self._state()
        self._requests[rid]=fingerprint;self._receipts[rid]='SENT'
        sent=False;first_returned=False
        try:
            self.portal.store.reserve(rid,fingerprint)
            self._persist({'status':'CREATING','request_id':rid,'adopted':False})
            self.portal.store.append({'kind':'request','request_id':rid,'approval_hash':None,'outcome':'SENT','http_status':None,'code':None})
            sent=True
            chat=self._upstream('POST','/api/chats',{})
            first_returned=True
            ident=chat.get('id')
            if not isinstance(ident,str) or not _CHAT.fullmatch(ident):raise _ShareError('UPSTREAM_CHAT_INVALID')
            self._persist({**self.portal.store.read(),'status':'CREATED','chat_id':ident})
            self._spec()
            chat=self._upstream('POST','/api/chat/context',{'chat_id':ident,'source':'','spec_path':str(self.portal.spec_path)})
            if chat.get('id')!=ident:raise _ShareError('UPSTREAM_CHAT_INVALID')
            self._bind(chat)
            self.portal.store.outcome(rid,'RECEIPT');self._receipts[rid]='RECEIPT';self._receipts[rid]='RECEIPT'
            self.portal.store.append({'kind':'response','request_id':rid,'approval_hash':None,'outcome':'RECEIPT','http_status':200,'code':None})
            return self._state()
        except Exception as exc:
            # A context rejection is still partial success: the chat already exists.
            known_rejection=(sent and not first_returned and isinstance(exc,_ShareError)
                             and exc.code=='UPSTREAM_REJECTED' and exc.status<500)
            outcome='REJECTED' if known_rejection else 'UNKNOWN'
            self._uncertain=not known_rejection;self._receipts[rid]=outcome
            try:
                self._persist({**self.portal.store.read(),'status':'NEW' if known_rejection else 'UNKNOWN'})
                self.portal.store.outcome(rid,outcome)
                self.portal.store.append({'kind':'response','request_id':rid,'approval_hash':None,'outcome':outcome,'http_status':exc.status if isinstance(exc,_ShareError) else 503,'code':exc.code if isinstance(exc,_ShareError) else 'PORTAL_STORE_FAILED'})
            except Exception:self._store_failed=True
            if not isinstance(exc,_ShareError):
                self._store_failed=True
                raise _ShareError('PORTAL_STORE_FAILED',503) from None
            if self._store_failed:raise _ShareError('PORTAL_STORE_FAILED',503) from None
            if not known_rejection and exc.status<500:raise _ShareError(exc.code,502) from None
            raise

    def _mutate(self,route,body):
        if self._store_failed:raise _ShareError('PORTAL_STORE_FAILED',503)
        if route=='/api/portal/chat':return self._create(body),200
        rid=body['request_id'];fingerprint=hashlib.sha256(_canonical({'route':route,'body':body})).hexdigest()
        previous=self._requests.get(rid)
        if previous:
            if previous!=fingerprint:raise _ShareError('REQUEST_CONFLICT',409)
            return {'state':self._state(),'chat':self._projection(self._chat()),'replayed':True},200
        if self._uncertain:raise _ShareError('PORTAL_REQUEST_UNKNOWN',409)
        binding=self.portal.store.read()
        if binding.get('status')!='CONTEXT_BOUND' and not (binding.get('status')=='CREATED' and binding.get('adopted')):raise _ShareError('PORTAL_CHAT_UNBOUND',409)
        reserved=False;sent=False
        try:
            chat=self._chat();ident=chat['id'];prep=chat.get('placement_preparation') or {};started=chat.get('placement_start')
            if binding.get('status')=='CREATED' and binding.get('adopted') and chat.get('proposal'):self._bind(chat)
            elif binding.get('status')=='CONTEXT_BOUND' and chat.get('mission_id')!=binding.get('mission_id'):self._bind(chat)
            if self.portal.store.read().get('status')!='CONTEXT_BOUND':raise _ShareError('PORTAL_ADOPTION_UNVERIFIED',409)
            if route in {'/api/portal/chat/prepare-placement','/api/portal/chat/start'} and not chat.get('proposal'):
                raise _ShareError('PORTAL_SPEC_UNVERIFIED',409)
            if route=='/api/portal/chat/message':
                if directive({'role':'user','text':body['message']}) or instruction(body['message'],chat.get('rsi_preparation')):
                    raise _ShareError('CHAT_DIRECTIVE_REJECTED',403)
                path='/api/chat/message';payload={**body,'chat_id':ident}
            elif route=='/api/portal/chat/prepare-placement':
                if not (chat.get('readiness') or {}).get('ready') or chat.get('mission_id') or prep:
                    raise _ShareError('PREPARATION_NOT_READY',409)
                if chat.get('approval_hash')!=body['approval_hash']:raise _ShareError('APPROVAL_MISMATCH',409)
                path='/api/chat/prepare-placement';payload={**body,'chat_id':ident}
            elif route=='/api/portal/chat/start':
                if prep.get('status')!='ACK' or started:raise _ShareError('START_REQUIRES_PREPARATION',409)
                if prep.get('approval_hash')!=body['approval_hash']:raise _ShareError('APPROVAL_MISMATCH',409)
                path='/api/chat/start';payload={**body,'chat_id':ident}
            elif route=='/api/portal/placement':
                mid=self._mission(chat)
                if prep.get('status')!='ACK' or started:raise _ShareError('PLACEMENT_AFTER_START',409)
                if body['node_id'] not in self.portal.node_allowlist:raise _ShareError('NODE_NOT_ALLOWLISTED',403)
                placement_view=self._placements(mid)
                tasks=placement_view['placements']
                if body['task_id'] not in [t.get('task_id',t.get('id')) for t in tasks]:raise _ShareError('TASK_NOT_IN_PLAN',400)
                if body['node_id'] not in [n['node_id'] for n in self._nodes(mid)['nodes'] if n['status']=='ACTIVE']:raise _ShareError('NODE_NOT_ACTIVE',409)
                path=f'/api/missions/{mid}/placements';payload=body
            else:
                path='/api/mission/message';payload={**body,'mission_id':self._mission(chat)}
            self.portal.store.reserve(rid,fingerprint)
            self._requests[rid]=fingerprint
            reserved=True
            self._receipts[rid]='SENT'
            self.portal.store.append({'kind':'request','request_id':rid,'approval_hash':body.get('approval_hash'),'outcome':'SENT','http_status':None,'code':None})
            sent=True  # The reservation and audit precede any mutating send.
            value=self._upstream('POST',path,payload)
            if path.startswith('/api/chat/'):
                if value.get('id')!=ident:raise _ShareError('UPSTREAM_CHAT_INVALID')
                self._guard(value)
                if route.endswith('prepare-placement'):
                    receipt=value.get('placement_preparation') or {}
                    if receipt.get('request_id')!=rid or receipt.get('scope')!='planning_only':raise _ShareError('UPSTREAM_RECEIPT_INVALID')
                if route.endswith('/start') and (value.get('placement_start') or {}).get('request_id')!=rid:raise _ShareError('UPSTREAM_RECEIPT_INVALID')
                if value.get('mission_id'):self._bind(value)
                value=self._projection(value)
            else:
                if value.get('request_id')!=rid:raise _ShareError('UPSTREAM_RECEIPT_INVALID')
                if path=='/api/mission/message' and value.get('status') not in {'RECEIVED','ANSWERED','APPLIED'}:raise _ShareError('UPSTREAM_RECEIPT_INVALID')
                if route=='/api/portal/placement':
                    if value.get('task_id')!=body['task_id'] or value.get('node_id')!=body['node_id'] or value.get('kind')!='remote':raise _ShareError('UPSTREAM_RECEIPT_INVALID')
                    value={'mission_id':self._mission(chat),'task_id':body['task_id'],'request_id':rid,'placement':self._public_placement(value)}
                else:value=_clean(value)
            self.portal.store.outcome(rid,'RECEIPT');self._receipts[rid]='RECEIPT'
            self.portal.store.append({'kind':'response','request_id':rid,'approval_hash':body.get('approval_hash'),'outcome':'RECEIPT','http_status':202 if path.startswith('/api/chat/') else 200,'code':None})
            return value,202 if path.startswith('/api/chat/') else 200
        except Exception as exc:
            known_rejection=isinstance(exc,_ShareError) and exc.code=='UPSTREAM_REJECTED' and exc.status<500
            outcome='UNKNOWN' if sent and not known_rejection else 'REJECTED'
            status=exc.status if isinstance(exc,_ShareError) else 503
            if outcome=='UNKNOWN' and status<500:status=502
            elif not sent and status>=500 and not self._store_failed:status=409
            try:
                if outcome=='UNKNOWN':self._uncertain=True
                if reserved:
                    self.portal.store.outcome(rid,outcome)
                    self._receipts[rid]=outcome
                self.portal.store.append({'kind':'response','request_id':rid,'approval_hash':body.get('approval_hash'),'outcome':outcome,'http_status':status,'code':exc.code if isinstance(exc,_ShareError) else 'PORTAL_INTERNAL_ERROR'})
            except Exception:self._store_failed=True
            if not isinstance(exc,_ShareError):
                self._store_failed=True
                raise _ShareError('PORTAL_STORE_FAILED',503) from None
            if status!=exc.status:
                code=exc.code if sent else 'PORTAL_PRESEND_READ_FAILED'
                raise _ShareError(code,status) from None
            raise

    def _upstream(self, method, path, body=None, *, engineering=False):
        self._active()
        deadline = share._Deadline()
        connection = share.HTTPConnection("127.0.0.1", self._upstream_port, timeout=deadline.remaining())
        response = None
        try:
            connection.connect()
            connection.sock = share._DeadlineSocket(connection.sock, deadline)
            headers = {"Authorization": "Bearer " + self._operator_token,
                       "Host": f"127.0.0.1:{self._upstream_port}",
                       "Origin": self._upstream_origin, "Connection": "close"}
            if engineering:
                headers["X-Sisyfus-Engineering-Result"] = "1"
            raw_body = _canonical(body) if body is not None else None
            if raw_body is not None:
                headers["Content-Type"] = "application/json"
            self._active()
            connection.request(method, path, body=raw_body, headers=headers)
            response = connection.getresponse()
            deadline.remaining()
            if 300 <= response.status < 400:
                raise _ShareError("UPSTREAM_REDIRECT_REJECTED")
            data = bytearray()
            while True:
                chunk = response.read(min(65_536, share.MAX_UPSTREAM_BYTES + 1 - len(data)))
                deadline.remaining()
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > share.MAX_UPSTREAM_BYTES:
                    raise _ShareError("UPSTREAM_BODY_TOO_LARGE")
            expected = 201 if method == "POST" and path == "/api/chats" else 202 if method == "POST" and path in {"/api/chat/message", "/api/chat/start", "/api/chat/prepare-placement"} else 200
            if response.status != expected:
                status = response.status if response.status in {400, 404, 409, 410, 413, 429} else 502
                raise _ShareError("UPSTREAM_REJECTED", status)
            types = response.headers.get_all("Content-Type", [])
            if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
                raise _ShareError("UPSTREAM_CONTENT_TYPE")
            result = _strict_json(bytes(data))
            if not isinstance(result, dict):
                raise _ShareError("UPSTREAM_JSON_SHAPE")
            _canonical(result)  # Also rejects overflowing/nonfinite parsed floats.
            if self._has_secret(result):
                raise _ShareError("UPSTREAM_CREDENTIAL_REJECTED")
            deadline.remaining()
            self._active()
            return result
        except _ShareError:
            raise
        except TimeoutError:
            raise _ShareError("UPSTREAM_TIMEOUT", 504) from None
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            raise _ShareError("UPSTREAM_JSON_INVALID") from None
        except Exception:
            raise _ShareError("UPSTREAM_IO_ERROR") from None
        finally:
            if response is not None:
                response.close()
            connection.close()


class _PortalHandler(_Handler):
    def _route(self):
        if len(self.path)>4096:raise _ShareError('QUERY_REJECTED',400)
        route=urlsplit(self.path)
        if route.scheme or route.netloc or route.fragment or route.path not in _ROUTES:raise _ShareError('ROUTE_NOT_FOUND',404)
        if route.path!='/api/portal/messages' and '?' in self.path:raise _ShareError('QUERY_REJECTED',400)
        return route

    def do_GET(self):
        try:
            self._boundary(auth=self.path!='/');route=self._route()
            if route.path=='/':
                from .portal_page import PAGE
                nonce=secrets.token_urlsafe(18)
                self._send(PAGE.replace('NONCE',nonce).encode(),content_type='text/html; charset=utf-8',nonce=nonce);return
            self._no_body()
            if route.path=='/api/portal/state':value=self.server._state()
            elif route.path=='/api/portal/chat':value=self.server._projection(self.server._chat())
            elif route.path=='/api/portal/report':
                if self.server._report is None:raise _ShareError('REPORT_ABSENT',404)
                raw=self.server._report.read()
                self._send(raw,content_type='text/html; charset=utf-8',report=True,protected=True);return
            elif route.path in {'/api/portal/placements','/api/portal/nodes','/api/portal/snapshot','/api/portal/messages'}:
                mid=self.server._mission(self.server._chat())
                if route.path.endswith('/placements'):value=self.server._placements(mid)
                elif route.path.endswith('/nodes'):value=self.server._nodes(mid)
                elif route.path.endswith('/snapshot'):value=self.server._snapshot_for(mid)
                else:
                    if re.search(r'%(?![0-9a-fA-F]{2})',route.query):raise _ShareError('QUERY_REJECTED',400)
                    q=parse_qs(route.query,keep_blank_values=True,strict_parsing=True,errors='strict',max_num_fields=2)
                    if set(q)-{'cursor','application_cursor'} or any(len(v)!=1 for v in q.values()):raise _ShareError('QUERY_REJECTED',400)
                    cursor=self._cursor(q.get('cursor',['0'])[0]);ac=self._cursor(q.get('application_cursor',['0'])[0])
                    value=self.server._upstream('GET',f'/api/mission/messages?mission_id={mid}&cursor={cursor}&application_cursor={ac}')
                    if (not isinstance(value.get('messages'),list) or not isinstance(value.get('updates'),list) or type(value.get('cursor')) is not int or value['cursor']<cursor or type(value.get('application_cursor')) is not int or value['application_cursor']<ac or type(value.get('has_more')) is not bool or type(value.get('has_more_updates')) is not bool):raise _ShareError('UPSTREAM_MESSAGES_INVALID')
                    value=_clean(value)
            else:raise _ShareError('METHOD_NOT_ALLOWED',405)
            self._json(value,protected=True)
        except _ShareError as exc:self._fail(exc.code,exc.status)
        except (ValueError,UnicodeError,TypeError,RecursionError,OverflowError):self._fail('REQUEST_REJECTED',400)
        except Exception:self._fail('PORTAL_INTERNAL_ERROR',500)

    def _portal_body(self,route):
        if route=='/api/portal/message':return self._body()
        value=self._json_body()
        keys={'/api/portal/chat':{'request_id'},'/api/portal/chat/message':{'request_id','message'},'/api/portal/chat/prepare-placement':{'request_id','approval_hash','allow_planning'},'/api/portal/chat/start':{'request_id','approval_hash','allow_local_workers'},'/api/portal/placement':{'request_id','task_id','node_id'}}[route]
        if not isinstance(value,dict) or set(value)!=keys:raise _ShareError('FIELDS_REJECTED',400)
        if not isinstance(value['request_id'],str) or not _REQUEST.fullmatch(value['request_id']):raise _ShareError('REQUEST_ID_REJECTED',400)
        if 'message' in keys and (not isinstance(value['message'],str) or not value['message'].strip() or len(value['message'])>4000):raise _ShareError('MESSAGE_SIZE_REJECTED',400)
        if 'approval_hash' in keys and (not isinstance(value['approval_hash'],str) or not _HASH.fullmatch(value['approval_hash'])):raise _ShareError('APPROVAL_HASH_REJECTED',400)
        for name in ('allow_planning','allow_local_workers'):
            if name in keys and value[name] is not True:raise _ShareError('EXPLICIT_PERMISSION_REQUIRED',403)
        if 'node_id' in keys and (not isinstance(value['node_id'],str) or not _NODE.fullmatch(value['node_id'])):raise _ShareError('NODE_ID_REJECTED',400)
        if 'task_id' in keys and (not isinstance(value['task_id'],str) or not value['task_id'] or len(value['task_id'].encode())>100):raise _ShareError('TASK_ID_REJECTED',400)
        return value

    def do_POST(self):
        locked=False
        try:
            self._boundary(auth=self.path!='/api/portal/login',post=True);route=self._route().path
            if route=='/api/portal/login':
                self.server._active();body=self._json_body()
                if not isinstance(body,dict) or set(body)!={'password'} or not isinstance(body['password'],str):raise _ShareError('PASSWORD_FIELDS_REJECTED',400)
                value=self.server._login(body['password']);self._credential=value['token'];self._json(value,protected=True,session=True);return
            if route=='/api/portal/logout':
                self._no_body();self.server._logout(self._credential);self._json({'status':'LOGGED_OUT'});return
            if route not in {'/api/portal/chat','/api/portal/chat/message','/api/portal/chat/prepare-placement','/api/portal/chat/start','/api/portal/placement','/api/portal/message'}:raise _ShareError('METHOD_NOT_ALLOWED',405)
            body=self._portal_body(route)
            locked=self.server._mutation_lock.acquire(blocking=False)
            if not locked:raise _ShareError('PORTAL_BUSY',409)
            self._authorize();value,status=self.server._mutate(route,body)
            self._json(value,status,protected=True)
        except _ShareError as exc:self._fail(exc.code,exc.status)
        except TimeoutError:self._fail('BODY_TIMEOUT',408)
        except (ValueError,UnicodeError,TypeError,RecursionError,OverflowError):self._fail('REQUEST_REJECTED',400)
        except Exception:self._fail('PORTAL_INTERNAL_ERROR',500)
        finally:
            if locked:self.server._mutation_lock.release()
