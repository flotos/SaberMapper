"""Explicit local WebGL integration check; requires installed ArcViewer and Chromium."""
import json
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect
from sabermapper.server import make_server


def main():
    with tempfile.TemporaryDirectory() as directory:
        server = make_server(directory, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=['--enable-webgl', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                external = []
                def local_only(route):
                    if urlparse(route.request.url).hostname not in {'127.0.0.1', 'localhost'}:
                        external.append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()
                context.route('**/*', local_only)
                page = context.new_page()
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base)
                page.locator('#create-demo').click()
                expect(page.locator('#project-title')).to_have_text('Neon Circuit')
                page.locator('#audio').evaluate('(audio)=>audio.currentTime=5')
                with page.expect_popup() as popup:
                    page.locator('#preview-map').click()
                viewer = popup.value
                errors = []
                viewer.on('pageerror', lambda e: errors.append(str(e)))
                viewer.wait_for_url('**/arcviewer/**')
                viewer.wait_for_function('window.gameInstance != null', timeout=60000)
                viewer.wait_for_function("document.title.includes('Neon Circuit')", timeout=30000)
                query = parse_qs(urlparse(viewer.url).query)
                assert query['t'] == ['5.0'] and query['noProxy'] == ['true'], query
                assert urlparse(query['url'][0]).netloc == urlparse(base).netloc
                assert context.request.get(query['url'][0]).body().startswith(b'PK')
                status = context.request.get(base + '/api/status').json()
                project = context.request.get(base + '/api/projects').json()[0]
                response = context.request.post(base + '/api/projects/' + project['id'] + '/preview',
                    headers={'X-SaberMapper-Token': status['token']}, data={'revision': 'stale', 'seconds': 0})
                assert response.status == 409
                # ArcViewer's first-use notice and controls are rendered in Unity canvas.
                viewer.wait_for_timeout(1200)
                viewer.mouse.click(940, 750, delay=100)
                viewer.wait_for_timeout(300)
                viewer.mouse.click(720, 610, delay=100)
                viewer.wait_for_timeout(300)
                viewer.mouse.click(260, 950, delay=100)
                viewer.wait_for_timeout(2500)
                Path('artifacts').mkdir(exist_ok=True)
                viewer.screenshot(path='artifacts/arcviewer-local.png')
                assert not errors, errors
                assert not external, external
                for path in ['/arcviewer/.git/config', '/arcviewer/%2e%2e/server.py']:
                    assert context.request.get(base + path).status != 200
                assert context.request.get(base + '/arcviewer/Build/ArcViewer.wasm', headers={'Range': 'bytes=0-7'}).headers['content-type'] == 'application/wasm'
                # A blocked popup still exposes a usable local link.
                page.evaluate('window.open=()=>null')
                page.locator('#preview-map').click()
                expect(page.locator('#busy')).not_to_be_visible()
                expect(page.locator('#arcviewer-open')).to_be_visible()
                assert page.locator('#arcviewer-open').get_attribute('href').startswith('/arcviewer/?')
                browser.close()
                print(json.dumps({'result': 'passed', 'external_requests': external, 'page_errors': errors}))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
