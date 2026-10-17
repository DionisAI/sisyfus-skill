"""Retained local-only runtime; synthetic verifier only."""
import json
import os
from test_portal_gateway import feature,verifier
import pytest


def setup_runtime(tmp_path,verifier):
    m=feature('portal_runtime');token=tmp_path/'token';token.write_text('fixture-operator-secret-long');token.chmod(0o600)
    password=tmp_path/'password.json';password.write_text(json.dumps(verifier));password.chmod(0o600)
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'source':str(tmp_path),'rsi':None}))
    return m.PortalRuntime('http://127.0.0.1:9999',token,tmp_path/'runtime',password_file=password,spec_file=spec,local_only=True)

def test_password_required_at_constructor(tmp_path):
    m=feature('portal_runtime')
    with pytest.raises((ValueError,TypeError)):m.PortalRuntime('http://127.0.0.1:9999',tmp_path/'token',tmp_path/'runtime',password_file=None,spec_file=tmp_path/'spec')

def test_exclusive_private_store_and_no_credentials(tmp_path,verifier):
    r=setup_runtime(tmp_path,verifier)
    try:
        meta=r.start();assert meta['schema']=='sisyfus.portal.runtime.v1' and meta['state']=='LOCAL_ONLY'
        assert meta['permissions']['start'] is True and meta['permissions']['inventory'] is False
        root=r.runtime_directory
        for name in ('portal.json','portal.jsonl','access.json'):
            assert (root/name).stat().st_mode & 0o777==0o600
            assert b'fixture-operator' not in (root/name).read_bytes()
        assert '#' not in json.loads((root/'access.json').read_text())['private_url']
        store=r._gateway.portal.store
        assert store.reserve('request_0001','a'*64);assert not store.reserve('request_0001','a'*64)
        with pytest.raises(ValueError):store.reserve('request_0001','b'*64)
        store.outcome('request_0001','UNKNOWN')
        assert 'UNKNOWN' in (root/'portal.json').read_text()
    finally:r.close()
    assert r.status()['resources_closed'] is True

def test_store_replacement_fails_not_success(tmp_path,verifier):
    r=setup_runtime(tmp_path,verifier)
    try:
        r.start();p=r.runtime_directory/'portal.json';p.rename(p.with_suffix('.retained'))
        p.write_text('{}');p.chmod(0o600)
        with pytest.raises(RuntimeError):r._gateway.portal.store.write({'status':'NEW'})
    finally:r.close()

def test_spec_link_rejected_before_publication(tmp_path,verifier):
    r=setup_runtime(tmp_path,verifier);p=r.spec_file;p.rename(p.with_suffix('.retained'));p.symlink_to(p.with_suffix('.retained'))
    with pytest.raises(Exception):r.start()
    assert r.status()['state']=='FAILED'
    r.close()

# v2 supplementary tests.
def test_store_same_inode_content_tamper_and_byte_limit(tmp_path,verifier):
    r=setup_runtime(tmp_path,verifier)
    try:
        r.start();p=r.runtime_directory/'portal.json';p.write_bytes(b'x'*1048577)
        with pytest.raises((RuntimeError,ValueError)):r._gateway.portal.store.read()
    finally:r.close()


def test_runtime_exclusive_directory_rejects_reuse(tmp_path,verifier):
    r=setup_runtime(tmp_path,verifier);r.runtime_directory.mkdir()
    with pytest.raises(Exception):r.start()
    assert r.status()['state']=='FAILED';r.close()

# v3: same-inode tamper must fence writes, not silently overwrite.
def test_store_same_inode_tamper_blocks_write(tmp_path,verifier):
    r=setup_runtime(tmp_path,verifier)
    try:
        r.start();p=r.runtime_directory/'portal.json';p.write_text('{}')
        with pytest.raises((RuntimeError,ValueError)):r._gateway.portal.store.write({'status':'NEW'})
    finally:r.close()
