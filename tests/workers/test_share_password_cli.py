"""Frozen password flag/binding cases: DI is not Gateway session/native/Cloudflare acceptance."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

VERIFIER = {"schema":"sisyfus.share.password.v1","kdf":"scrypt","n":131072,"r":8,"p":1,"salt":"12"*16,"digest":"34"*32}
OPERATOR = "password-runtime-operator-fixture-b411dd8d"
SHARE = "password-runtime-share-fixture-7709afff"


def metadata(state):
    return {"schema":"sisyfus.share.runtime.v1","state":state,"local_origin":"http://127.0.0.1:12345","public_origin":None,"access_file":"/private/tmp/owned/access.json","permissions":{"messages":False,"controls":False},"resources_closed":state=="CLOSED","process_returncode":None,"diagnostics":[]}


def args(tmp_path):
    return ["--console-origin","http://127.0.0.1:12345","--operator-token-file",str(tmp_path/'operator.token'),"--mission-id","fixture","--runtime-directory",str(tmp_path/'runtime')]


class RuntimeDI:
    def __init__(self, *values, **options):
        self.values, self.options = values, options
        self.closed = 0
    def start(self):
        return metadata("LOCAL_ONLY")
    def status(self):
        return metadata("CLOSED")
    def close(self):
        self.closed += 1
        return metadata("CLOSED")


@pytest.mark.parametrize("password", [False, True])
def test_cli_conditional_password_kw_and_original_exact_default_DI(tmp_path, capsys, password):
    module=importlib.import_module('sisyfus.workers.share_cli')
    made=[]
    def factory(*values, **options):
        result=RuntimeDI(*values, **options);made.append(result);return result
    argv=args(tmp_path)
    target=tmp_path/'password-verifier.json'
    if password:argv += ['--password-file',str(target)]
    assert module.main(argv,runtime_factory=factory,sleep=lambda seconds:None)==0
    assert len(made)==1 and made[0].closed==1
    expected={'allow_messages':False,'report_path':None,'local_only':False,'cloudflared':'cloudflared','startup_timeout':30.0}
    if password:expected['password_file']=str(target)
    assert made[0].options==expected
    assert not (tmp_path/'runtime').exists() and not target.exists()
    output=capsys.readouterr();assert not output.err and str(target) not in output.out


@pytest.mark.parametrize('tail',[
 ['--password-file','relative.json'],['--password-file',''],
 ['--password-file','/private/tmp/../secret.json'],['--password-file','//remote/share/verifier.json'],
 ['--password-file','/private/tmp/./secret.json'],['--password-file','/private/tmp/x\0.json'],
 ['--password-file','/private/tmp/a.json','--password-file','/private/tmp/b.json'],
 ['--password','synthetic-only-not-argv'],['--password-file'],
])
def test_cli_bad_password_flags_before_factory_no_raw_echo(tmp_path,capsys,tail):
    module=importlib.import_module('sisyfus.workers.share_cli');calls=[]
    def forbidden(*values,**options):calls.append(True);raise AssertionError('must not construct')
    assert module.main(args(tmp_path)+tail,runtime_factory=forbidden)==1
    assert not calls and not (tmp_path/'runtime').exists()
    output=capsys.readouterr();assert not output.out
    assert json.loads(output.err)=={'status':'ERROR','stage':'parse','error_type':'ValueError'}
    assert 'synthetic-only-not-argv' not in output.err and 'secret.json' not in output.err


def test_cli_password_help_has_no_constructor_or_file_reads(tmp_path,capsys):
    module=importlib.import_module('sisyfus.workers.share_cli')
    def forbidden(*values,**options):pytest.fail('help must not construct/read verifier')
    assert module.main(['--help'],runtime_factory=forbidden)==0
    output=capsys.readouterr();assert not output.err and '--password-file' in output.out
    assert not list(tmp_path.iterdir())


def test_lead_share_parser_and_lazy_dispatch_password_flag(tmp_path,monkeypatch):
    lead=importlib.import_module('sisyfus.workers.lead_cli');received=[]
    def forward(argv):received.append(list(argv));return 17
    monkeypatch.setitem(sys.modules,'sisyfus.workers.share_cli',SimpleNamespace(main=forward))
    target=str(tmp_path/'verifier.json')
    assert lead.main(['share','--password-file',target])==17
    assert received==[['--password-file',target]]
    parsed=lead.parser().parse_args(['share','--password-file',target])
    assert parsed.command=='share' and str(parsed.password_file)==target
    assert not list(tmp_path.iterdir())


class Gateway:
    """Owned Thread-only public protocol, not successful password/session HTTP admission."""
    def __init__(self, origin, token, mission, *, port, allow_messages, report_path):
        assert token==OPERATOR
        self.origin='http://127.0.0.1:12346';self.url=self.origin+'/';self.token=SHARE
        self.stop=threading.Event();self.revoked=False;self.closed=False
    def serve_forever(self,*,poll_interval):assert self.stop.wait(5)
    def shutdown(self):self.stop.set()
    def server_close(self):self.closed=True
    def revoke(self):self.revoked=True
    def set_public_origin(self,origin):self.public_origin=origin


def inputs(tmp_path):
    token=tmp_path/'operator.token';fd=os.open(token,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:os.write(fd,(OPERATOR+'\n').encode())
    finally:os.close(fd)
    verifier=tmp_path/'verifier.json'
    importlib.import_module('sisyfus.workers.share_password').save_verifier(verifier,VERIFIER)
    return token,verifier,tmp_path/'runtime'


def unchanged(path):return path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns


def test_public_runtime_password_binding_plain_link_and_no_verifier_copy(tmp_path):
    module=importlib.import_module('sisyfus.workers.share_runtime');token,verifier,root=inputs(tmp_path)
    before=unchanged(verifier);operator=unchanged(token);received=[];gateways=[]
    def factory(origin,credential,mission,*,port,allow_messages,report_path,password_verifier):
        received.append(password_verifier);result=Gateway(origin,credential,mission,port=port,allow_messages=allow_messages,report_path=report_path);gateways.append(result);return result
    run=module.ShareRuntime('http://127.0.0.1:12345',token,'fixture',root,local_only=True,password_file=verifier,gateway_factory=factory)
    try:
        meta=run.start();assert meta['state']=='LOCAL_ONLY'
        assert received==[VERIFIER] and received[0] is not VERIFIER
        access=json.loads(Path(meta['access_file']).read_bytes())
        assert access['private_url']==meta['local_origin']+'/'
        assert not urlsplit(access['private_url']).fragment
        assert sorted(x.name for x in root.iterdir())==['access.json','runtime.log','state.json']
        serial=json.dumps(meta)+''.join(x.read_text() for x in root.iterdir())
        assert OPERATOR not in serial and SHARE not in serial and VERIFIER['salt'] not in serial and VERIFIER['digest'] not in serial
    finally:closed=run.close()
    assert closed['resources_closed'] and gateways[0].closed and gateways[0].revoked
    assert unchanged(verifier)==before and unchanged(token)==operator


def test_public_runtime_default_old_factory_kwargs_and_bearer_link_unchanged(tmp_path):
    module=importlib.import_module('sisyfus.workers.share_runtime');token,verifier,root=inputs(tmp_path)
    received=[]
    def old_factory(origin,credential,mission,*,port,allow_messages,report_path):
        received.append((port,allow_messages,report_path));return Gateway(origin,credential,mission,port=port,allow_messages=allow_messages,report_path=report_path)
    run=module.ShareRuntime('http://127.0.0.1:12345',token,'fixture',root,local_only=True,gateway_factory=old_factory)
    try:
        meta=run.start();access=json.loads(Path(meta['access_file']).read_bytes())
        assert received==[(0,False,None)] and access['private_url']==meta['local_origin']+'/#token='+SHARE
    finally:run.close()


@pytest.mark.parametrize('failure',['missing','malformed','cost','mode','leaflink'])
def test_runtime_bad_verifier_admission_before_artifacts_and_factory(tmp_path,failure):
    module=importlib.import_module('sisyfus.workers.share_runtime');token,verifier,root=inputs(tmp_path);calls=[]
    selected=verifier
    if failure=='missing':selected=tmp_path/'absent.json'
    if failure=='malformed':verifier.write_bytes(b'not a verifier')
    if failure=='cost':value=dict(VERIFIER,n=16);verifier.write_text(json.dumps(value))
    if failure=='mode':os.chmod(verifier,0o644)
    if failure=='leaflink':selected=tmp_path/'alias.json';selected.symlink_to(verifier)
    before=unchanged(verifier);operator=unchanged(token)
    def forbidden(*values,**options):calls.append(True);pytest.fail('invalid verifier must precede binding/artifacts')
    run=module.ShareRuntime('http://127.0.0.1:12345',token,'fixture',root,local_only=True,password_file=selected,gateway_factory=forbidden)
    try:
        with pytest.raises(module.ShareRuntimeError) as failure_info:run.start()
        assert failure_info.value.stage=='password.read'
        assert not root.exists() and not calls
    finally:run.close()
    assert unchanged(verifier)==before and unchanged(token)==operator


@pytest.mark.parametrize('path',['relative.json','/private/tmp/../x.json','/private/tmp/x\0.json'])
def test_runtime_password_path_admission_is_pure_before_IO(tmp_path,path):
    module=importlib.import_module('sisyfus.workers.share_runtime');calls=[]
    with pytest.raises(ValueError):module.ShareRuntime('http://127.0.0.1:12345',tmp_path/'operator.token','fixture',tmp_path/'runtime',password_file=path,gateway_factory=lambda *a,**k:calls.append(True))
    assert not list(tmp_path.iterdir()) and not calls


def test_runtime_verifier_not_in_child_argv_env_or_retained_artifacts(tmp_path,monkeypatch):
    module=importlib.import_module('sisyfus.workers.share_runtime');token,verifier,root=inputs(tmp_path)
    source=Path(__file__).resolve().parents[2]/'artifacts/techlead/orchestra-20261007/cloudflare-share-reaped-group-sol-8ca0847b4c4f4fadb898ab7de28f59f6/test_reaped_group.py'
    spec=importlib.util.spec_from_file_location('frozen_p3_protocol',source);fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    child=fixture.Process();proxy=fixture.OSProxy(child);captured=[]
    def popen(argv,**options):captured.append((argv,options));return child
    monkeypatch.setattr(module,'subprocess',SimpleNamespace(Popen=popen,PIPE=subprocess.PIPE,TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(module,'os',proxy)
    def factory(origin,credential,mission,*,port,allow_messages,report_path,password_verifier):
        assert password_verifier==VERIFIER
        return Gateway(origin,credential,mission,port=port,allow_messages=allow_messages,report_path=report_path)
    before=unchanged(verifier)
    run=module.ShareRuntime('http://127.0.0.1:12345',token,'fixture',root,password_file=verifier,gateway_factory=factory,cloudflared=str(tmp_path/'fixture-cloudflared'),startup_timeout=30)
    try:
        meta=run.start();assert meta['state']=='CONNECTED' and len(captured)==1
        argv,options=captured[0];transport=json.dumps({'argv':argv,'env':options['env'],'cwd':str(options['cwd'])})
        assert str(verifier) not in transport and VERIFIER['salt'] not in transport and VERIFIER['digest'] not in transport
        assert OPERATOR not in transport and SHARE not in transport and options['start_new_session'] and not options['shell']
        assert json.loads((root/'access.json').read_bytes())['private_url']==meta['public_origin']+'/'
        for item in root.rglob('*'):
            if item.is_file():
                raw=item.read_bytes();assert VERIFIER['salt'].encode() not in raw and VERIFIER['digest'].encode() not in raw
    finally:closed=run.close()
    assert closed['resources_closed'] and child.stdin.closed and child.stdout.closed and child.stderr.closed
    assert unchanged(verifier)==before
