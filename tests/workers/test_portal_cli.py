from test_portal_gateway import feature
import pytest

def args():return ['--console-origin','http://127.0.0.1:9999','--operator-token-file','/fixture/token','--runtime-directory','/fixture/new','--password-file','/fixture/password','--spec-file','/fixture/spec','--local-only']

def test_cli_help_and_required_password_parse_only(capsys):
    m=feature('portal_cli');assert m.main(['--help'])==0
    assert '--spec-file' in capsys.readouterr().out
    assert m._parse(args()).local_only is True
    a=args();del a[6:8]
    with pytest.raises(ValueError):m._parse(a)

@pytest.mark.parametrize('tail',[['--spec-file','/another'],['--mission-id','other'],['--node-id','node_invalid'],['--chat-id','c_invalid'],['--allow-messages'],['--local-only']])
def test_extra_repeated_or_invalid_flags_rejected(tail):
    m=feature('portal_cli')
    with pytest.raises(ValueError):m._parse(args()+tail)

def test_metadata_never_confuses_share_contract():
    m=feature('portal_cli')
    with pytest.raises(ValueError):m._public({'schema':'sisyfus.share.runtime.v1'})
