"""Frozen N2/N4 exact identity-header boundary, before the integration repair.

Real Handler and bound hub, socket-free. A valid operator Bearer plus the N4
X-Sisyfus-Node identity is still node-origin input, never backend-init authority.
Unrelated ordinary X-Sisyfus headers remain accepted. No native dispatch.
"""
from __future__ import annotations

import pytest

from sisyfus.workers.lead_console import MissionHub
from test_lead_mission import make_spec
from test_node_operator_http import backend_tables, call, nodes, placements


@pytest.fixture
def hub(tmp_path):
    h = MissionHub(tmp_path / 'hub')
    ident = h.create(make_spec(tmp_path))['id']
    h._session(ident).mission._initial_plan()
    yield h, ident
    h.close()


@pytest.mark.parametrize('header', ['X-Sisyfus-Node', 'x-sisyfus-node'])
@pytest.mark.parametrize('route', ['inventory', 'enroll', 'revoke', 'placement'])
def test_exact_n4_node_header_rejects_every_operator_route_before_init(hub, header, route):
    h, ident = hub
    m = h._session(ident).mission
    assert not backend_tables(m)
    before = m.store.verify_event_chain()
    path, method, body = nodes(ident), 'GET', None
    if route == 'enroll':
        method, body = 'POST', {'request_id': 'header_enroll_001', 'name': 'header fixture'}
    elif route == 'revoke':
        path, method, body = nodes(ident) + '/node_' + 'a' * 32 + '/revoke', 'POST', {}
    elif route == 'placement':
        path, method, body = placements(ident), 'POST', {
            'request_id': 'header_place_001', 'task_id': 'build', 'node_id': 'node_' + 'a' * 32}
    result = call(h, path, method=method, body=body, headers=[(header, 'node_' + 'a' * 32)])
    assert result[0] == 403
    assert not backend_tables(m) and not (m.directory / 'remote').exists()
    assert not m.journal.runs() and m.store.verify_event_chain() == before


def test_ordinary_operator_and_unrelated_sisyfus_headers_keep_all_routes(hub):
    h, ident = hub
    headers = [('X-Sisyfus-Trace', 'ordinary'), ('X-Sisyfus-Operator', 'ordinary'),
               ('X-Sisyfus-Nodes', 'ordinary'), ('X-Sisyfus-Nodeish', 'ordinary')]
    assert call(h, nodes(ident), headers=headers)[0] == 200
    status, node = call(h, nodes(ident), method='POST', headers=headers,
                       body={'request_id': 'header_enroll_001', 'name': 'ordinary fixture'})
    assert status == 201
    status, pin = call(h, placements(ident), method='POST', headers=headers, body={
        'request_id': 'header_place_001', 'task_id': 'build', 'node_id': node['node_id']})
    assert status == 200 and pin['execution_ready'] is False
    status, revoked = call(h, nodes(ident) + '/' + node['node_id'] + '/revoke',
                           method='POST', headers=headers, body={})
    assert status == 200 and revoked['status'] == 'REVOKED'
    assert not h._session(ident).mission.journal.runs()
