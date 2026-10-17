"""Frozen vertical tracer: public two-prompt setup -> strict private verifier -> actual scrypt verify."""
import importlib
import json
import os
import re
import stat


def test_public_password_setup_verifier_roundtrip_no_plaintext(tmp_path, capsys):
    module = importlib.import_module("sisyfus.workers.share_password")
    selected = "synthetic-only-访问密码-7bb0344a"
    prompts = []
    def password(prompt):
        assert isinstance(prompt, str) and prompt
        prompts.append(prompt)
        return selected
    target = tmp_path / "verifier.json"
    assert module.main(["--output", str(target)], get_password=password) == 0
    assert len(prompts) == 2
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == {"status":"CREATED","verifier_file":str(target)}
    raw = target.read_bytes()
    assert len(raw) <= 4096 and selected.encode() not in raw
    info = target.lstat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 1 and info.st_uid == os.getuid()
    verifier = module.load_verifier(target)
    assert set(verifier) == {"schema","kdf","n","r","p","salt","digest"}
    assert {k:verifier[k] for k in ("schema","kdf","n","r","p")} == {"schema":"sisyfus.share.password.v1","kdf":"scrypt","n":131072,"r":8,"p":1}
    assert re.fullmatch(r"[0-9a-f]{32}", verifier["salt"])
    assert re.fullmatch(r"[0-9a-f]{64}", verifier["digest"])
    assert module.verify_password(selected, verifier) is True
    assert module.verify_password(selected + "-wrong", verifier) is False
    copy = module.validate_verifier(verifier)
    assert copy == verifier and copy is not verifier
    copy["digest"] = "0" * 64
    assert copy != verifier
    assert selected not in output.out + output.err
    assert verifier["salt"] not in output.out + output.err and verifier["digest"] not in output.out + output.err
