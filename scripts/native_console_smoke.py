"""Browser/HTTP smoke against actual persisted protocol-fixture data, never LLMs."""
from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from sisyfus.workers.cli import demo_spec
from sisyfus.workers.console import Console
from sisyfus.workers.mission import Mission, load_spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    root = args.directory.resolve()
    spec = demo_spec(root / 'demo')
    mission = Mission(root / 'demo' / 'control', load_spec(spec))
    result = mission.run()
    assert result['all_verified'] and result['native_call_reservations'] == 4
    server = Console(mission, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=args.browser_executable)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(server.url)
            expect(page.locator("#connection")).to_contain_text("LIVE")
            assert page.locator('.node').count() == 2
            assert page.locator('.attempt').count() == 4
            assert page.locator('.attempt.fail').count() == 1
            assert page.locator('.attempt.pass').count() == 2
            page.locator('.node').first.click()
            assert 'PASS' in page.locator('#detail').inner_text()
            page.screenshot(path=str(root / 'desktop.png'), full_page=True)
            page.locator('#pause').click()
            expect(page.locator("#kind")).to_contain_text("PAUSED")
            assert mission.journal.paused()
            page.locator('#resume').click()
            expect(page.locator("#kind")).not_to_contain_text("PAUSED")
            assert not mission.journal.paused()
            assert '#token=' not in page.url
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(root / 'mobile.png'), full_page=True)
            assert not errors, errors
            browser.close()
        report = {'all_verified': result['all_verified'], 'native_invocations': 4,
                  'real_llm_executed': False, 'browser_errors': errors,
                  'historical_attempt_verdicts': [r['verdict'] for r in result['runs']],
                  'pause_resume_verified_in_database': True, 'token_removed_from_address_bar': True,
                  'chain': mission.store.verify_event_chain()}
        (root / 'browser-validation.json').write_text(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
