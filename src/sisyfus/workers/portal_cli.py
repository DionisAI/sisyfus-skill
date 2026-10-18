"""Separate opt-in foreground portal CLI. Help/parse perform no IO."""
from __future__ import annotations
import argparse
import json
import math
import os
import time
from .share_cli import _Parser,_Once,_origin,_failure,_STATES
from .portal_gateway import _CHAT,_NODE


def _parse(argv):
    p=_Parser(prog='python -m sisyfus.workers.portal_cli',allow_abbrev=False,add_help=False,description='单工程手机入口：密码必需，规划和执行分别确认。Stop 留本机控制器。')
    p.add_argument('-h','--help',action='store_true');opts={'action':_Once,'default':argparse.SUPPRESS}
    for flag in ('console-origin','operator-token-file','runtime-directory','password-file','spec-file','chat-id','report','cloudflared','startup-timeout'):p.add_argument('--'+flag,**opts)
    p.add_argument('--local-only',nargs=0,**opts);p.add_argument('--node-id',action='append',default=[])
    a=p.parse_args(argv)
    if a.help:p.print_help();return None
    for k in ('console_origin','operator_token_file','runtime_directory','password_file','spec_file'):
        value=getattr(a,k,None)
        if not value:raise ValueError('required flag')
        if k!='console_origin' and (not os.path.isabs(value) or value.startswith('//') or '\0' in value or any(v in {'.','..'} for v in value.split('/'))):raise ValueError('absolute path')
    _origin(a.console_origin)
    a.chat_id=getattr(a,'chat_id',None)
    if a.chat_id is not None and not _CHAT.fullmatch(a.chat_id):raise ValueError('chat id')
    if len(a.node_id)>4 or len(set(a.node_id))!=len(a.node_id) or any(not _NODE.fullmatch(x) for x in a.node_id):raise ValueError('node ids')
    a.startup_timeout=float(getattr(a,'startup_timeout',30.0))
    if not math.isfinite(a.startup_timeout) or a.startup_timeout<=0:raise ValueError('timeout')
    a.local_only=getattr(a,'local_only',False);a.report=getattr(a,'report',None);a.cloudflared=getattr(a,'cloudflared','cloudflared')
    return a


def _public(value):
    if not isinstance(value,dict) or value.get('schema')!='sisyfus.portal.runtime.v1' or value.get('state') not in _STATES:raise ValueError('portal metadata')
    permissions=value.get('permissions')
    keys={'view','messages','chat','planning','start','placement','controls','inventory'}
    if not isinstance(permissions,dict) or set(permissions)!=keys or any(type(x) is not bool for x in permissions.values()) or any(permissions[k] is not True for k in ('view','messages','chat','planning','start')) or permissions['controls'] or permissions['inventory']:raise ValueError('portal permissions')
    # Reuse validated transport fields, never confuse the public schemas.
    from .share_cli import _public as share_public
    transport=share_public({**value,'schema':'sisyfus.share.runtime.v1','permissions':{'messages':True,'controls':False}})
    return {**transport,'schema':'sisyfus.portal.runtime.v1','permissions':dict(permissions)}


def main(argv=None,*,runtime_factory=None,sleep=None):
    owned=None;stage='parse';result=0
    def emit(value):
        value=_public(value);print(json.dumps(value,ensure_ascii=False),flush=True);return value
    try:
        a=_parse(argv)
        if a is None:return 0
        if runtime_factory is None:
            from .portal_runtime import PortalRuntime
            runtime_factory=PortalRuntime
        stage='construct';owned=runtime_factory(a.console_origin,a.operator_token_file,a.runtime_directory,password_file=a.password_file,spec_file=a.spec_file,adopt_chat_id=a.chat_id,node_ids=tuple(a.node_id),report_path=a.report,local_only=a.local_only,cloudflared=a.cloudflared,startup_timeout=a.startup_timeout)
        stage='start';last=emit(owned.start());pause=time.sleep if sleep is None else sleep
        while last['state'] not in {'FAILED','CLOSED'}:
            stage='status';current=_public(owned.status())
            if current!=last:last=emit(current)
            if last['state'] not in {'FAILED','CLOSED'}:stage='sleep';pause(.2)
        if last['state']=='FAILED':result=1
    except BaseException as exc:_failure(stage,exc);result=130 if isinstance(exc,KeyboardInterrupt) else 1
    finally:
        if owned is not None:
            try:emit(owned.close())
            except BaseException as exc:_failure('close',exc);result=130 if isinstance(exc,KeyboardInterrupt) else 1
    return result

if __name__=='__main__':raise SystemExit(main())
