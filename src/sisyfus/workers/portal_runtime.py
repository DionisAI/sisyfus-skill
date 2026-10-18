"""Owned publication lifecycle; retained PortalStore records binding, never truth."""
from __future__ import annotations
import copy
import hashlib
import os
import re
import threading
from .share_runtime import ShareRuntime, _path, _regular
from .share_gateway import _canonical
from .portal_gateway import OperatorPortalGateway,PortalConfig,_CHAT,_NODE,_REQUEST,_HASH

LIMIT=1048576

class PortalStore:
    """Exclusive private files using the original Runtime identity/write discipline."""
    def __init__(self,owner):
        self.owner=owner;self.lock=threading.RLock();self._binding={'status':'NEW'};self._requests={};self._bytes=0
        owner._new_file('portal.json');owner._new_file('portal.jsonl');self._flush()
        os.fsync(owner._root_fd)

    def _flush(self):
        if hasattr(self,'_pin'):self.read()
        payload=_canonical({'schema':'sisyfus.portal.binding.v1','binding':self._binding,'requests':self._requests})
        if len(payload)>LIMIT:raise ValueError('portal store capacity')
        self.owner._write('portal.json',payload+b'\n')
        self._pin=hashlib.sha256(payload+b'\n').hexdigest()

    def read(self):
        with self.lock:
            fd=self.owner._checked_file('portal.json')
            size=os.fstat(fd).st_size
            if size>LIMIT or hashlib.sha256(os.pread(fd,size+1,0)).hexdigest()!=self._pin:raise RuntimeError('binding content changed')
            return copy.deepcopy(self._binding)

    def write(self,value):
        with self.lock:
            allowed={'status','chat_id','adopted','request_id','source','spec_path','rsi_configuration','mission_id'}
            if not isinstance(value,dict) or set(value)-allowed:raise ValueError('binding fields')
            self._binding=copy.deepcopy(value);self._flush()

    def reserve(self,rid,fingerprint):
        with self.lock:
            if not _REQUEST.fullmatch(rid) or not _HASH.fullmatch(fingerprint):raise ValueError('request pin')
            old=self._requests.get(rid)
            if old:
                if old['fingerprint']!=fingerprint:raise ValueError('request conflict')
                return False
            self._requests[rid]={'fingerprint':fingerprint,'outcome':'SENT'};self._flush();return True

    def outcome(self,rid,outcome):
        with self.lock:
            if outcome not in {'SENT','RECEIPT','REJECTED','UNKNOWN'}:raise ValueError('outcome')
            self._requests[rid]['outcome']=outcome;self._flush()

    def append(self,event):
        with self.lock:
            if not isinstance(event,dict) or set(event)!={'kind','request_id','approval_hash','outcome','http_status','code'}:raise ValueError('audit fields')
            if event['kind'] not in {'request','response'} or not _REQUEST.fullmatch(event['request_id']) or event['outcome'] not in {'SENT','RECEIPT','REJECTED','UNKNOWN'}:raise ValueError('audit shape')
            if event['approval_hash'] is not None and not _HASH.fullmatch(event['approval_hash']):raise ValueError('audit hash')
            if event['code'] is not None and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',event['code']):raise ValueError('audit code')
            if event['http_status'] is not None and (type(event['http_status']) is not int or not 100<=event['http_status']<=599):raise ValueError('audit status')
            raw=_canonical(event)+b'\n'
            if self._bytes+len(raw)>LIMIT:raise ValueError('audit capacity')
            fd=self.owner._checked_file('portal.jsonl')
            if os.fstat(fd).st_size!=self._bytes:raise RuntimeError('audit file changed')
            os.lseek(fd,0,os.SEEK_END);view=memoryview(raw)
            while view:
                count=os.write(fd,view)
                if count<=0:raise OSError('audit write')
                view=view[count:]
            os.fsync(fd);self._bytes+=len(raw)


class PortalRuntime(ShareRuntime):
    def __init__(self,console_origin,operator_token_file,runtime_directory,*,password_file,spec_file,adopt_chat_id=None,node_ids=(),report_path=None,local_only=False,cloudflared='cloudflared',startup_timeout=30.0):
        if password_file is None:raise ValueError('portal password required')
        self.spec_file=_path(spec_file,absolute=True);self.adopt_chat_id=adopt_chat_id;self.node_ids=tuple(node_ids)
        if adopt_chat_id is not None and (not isinstance(adopt_chat_id,str) or not _CHAT.fullmatch(adopt_chat_id)):raise ValueError('adopt chat')
        if len(self.node_ids)>4 or len(set(self.node_ids))!=len(self.node_ids) or any(not isinstance(x,str) or not _NODE.fullmatch(x) for x in self.node_ids):raise ValueError('node ids')
        def factory(*args,**kwargs):
            raw=_regular(self.spec_file,200000)
            pin=hashlib.sha256(raw).hexdigest()
            store=PortalStore(self)
            config=PortalConfig(self.spec_file,pin,self.adopt_chat_id,self.node_ids,store)
            return OperatorPortalGateway(*args,**kwargs,portal=config)
        super().__init__(console_origin,operator_token_file,'portal',runtime_directory,password_file=password_file,allow_messages=True,report_path=report_path,local_only=local_only,cloudflared=cloudflared,startup_timeout=startup_timeout,gateway_factory=factory)

    def _permissions(self):return {'view':True,'messages':True,'chat':True,'planning':True,'start':True,'placement':bool(self.node_ids),'controls':False,'inventory':False}

    def _metadata(self):
        value=super()._metadata();value.update(schema='sisyfus.portal.runtime.v1',permissions=self._permissions());return value

    def _access(self,origin):
        self._write('access.json',_canonical({'schema':'sisyfus.portal.access.v1','permissions':self._permissions(),'private_url':origin+'/'})+b'\n')
