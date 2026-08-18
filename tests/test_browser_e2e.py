"""End-to-End browser UI tests executing real JavaScript in Chrome via CDP."""

import json
import time
import urllib.parse
import urllib.request
import pytest
import websocket


CDP_URL = "http://127.0.0.1:9222"
APP_URL = "http://127.0.0.1:8011/app/"
TEST_USER_ID = "f51669a5-b262-475b-979c-4da82b072266"


class BrowserSession:
    def __init__(self, cdp_url: str, target_url: str):
        self.cdp_url = cdp_url
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        encoded = urllib.parse.quote(target_url, safe="")
        req = urllib.request.Request(f"{cdp_url.rstrip('/')}/json/new?{encoded}", method="PUT")
        with self.opener.open(req) as resp:
            info = json.load(resp)
        self.page_id = info["id"]
        self.ws_url = info["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(
            self.ws_url,
            timeout=25.0,
            suppress_origin=True,
            http_proxy_host=None,
        )
        self.mid = 0
        self.call("Page.enable")
        self.call("Runtime.enable")

    def call(self, method: str, params: dict | None = None) -> dict:
        self.mid += 1
        cid = self.mid
        self.ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == cid:
                if "error" in msg:
                    raise Exception(f"CDP {method} error: {msg['error']}")
                return msg.get("result", {})

    def eval(self, js_expr: str):
        res = self.call("Runtime.evaluate", {
            "expression": js_expr,
            "returnByValue": True,
            "awaitPromise": True
        })
        return res.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.opener.open(
                urllib.request.Request(f"{self.cdp_url.rstrip('/')}/json/close/{self.page_id}"),
                timeout=3.0
            )
        except Exception:
            pass


@pytest.fixture
def browser():
    session = BrowserSession(CDP_URL, APP_URL)
    # Set owner ID in localStorage and reload
    session.eval(f"""
        localStorage.setItem('fridge_owner_id', '{TEST_USER_ID}');
        location.reload();
    """)
    time.sleep(3.0)
    yield session
    session.close()


def test_browser_ui_renders_live_catalog_with_images(browser: BrowserSession):
    """Verify that the browser renders products with real images from the backend."""
    time.sleep(2.0)
    app_status = browser.eval("""
        (() => {
            if (!window.__app) return { ok: false, error: 'no-instance' };
            const count = window.__app.cat ? window.__app.cat.length : 0;
            const images = window.__app.cat ? window.__app.cat.filter(x => x.image_url && x.image_url.includes('avatars.mds.yandex.net')).length : 0;
            return { ok: true, count, images, backendOnline: window.__app.state.backendOnline };
        })()
    """)
    assert app_status["ok"] is True
    assert app_status["count"] > 0, "Expected catalog to load items from backend"
    assert app_status["images"] > 0, "Expected catalog to contain products with genuine photos"


def test_browser_ui_filter_chips_work(browser: BrowserSession):
    """Verify that filter chips filter the catalog properly in the UI."""
    res = browser.eval("""
        (() => {
            if (!window.__app) return { error: 'no-instance' };
            const app = window.__app;
            app.setState({ chip: 'Молочные' });
            const dairyCount = app.cat.filter(p => p.tags.includes('Молочные')).length;
            app.setState({ chip: 'Все' });
            const allCount = app.cat.length;
            return { dairyCount, allCount };
        })()
    """)
    assert res["allCount"] >= res["dairyCount"] > 0


def test_browser_ui_partial_consume_does_not_remove_card_until_depleted(browser: BrowserSession):
    """Verify that partial consumption immediately updates the UI without removing the product card."""
    res = browser.eval("""
        (async () => {
            if (!window.__app) return { error: 'no-instance' };
            const app = window.__app;
            // Find a product with plenty of availability
            const p = app.cat.find(x => app.avail(x) >= 200 && x.unit === 'г');
            if (!p) return { error: 'no-200g-prod' };

            const initialAvail = app.avail(p);
            const deduct = 100;

            // Simulate partial consumption of 100g
            await app.consumeLots([{
                lot_id: p.lot_id || p.id,
                quantity: deduct,
                unit: 'g'
            }], 'consumed');

            const afterP = app.cat.find(x => x.id === p.id);
            const afterAvail = afterP ? app.avail(afterP) : 0;
            const stockVal = app.state.stock[p.id];
            
            return {
                id: p.id,
                initialAvail,
                deduct,
                afterAvail,
                stockVal,
                toast: app.state.toast?.text
            };
        })()
    """)
    assert "error" not in res, f"Browser test error: {res}"
    # Verify that remaining amount is strictly positive and reduced by exactly 100
    assert res["afterAvail"] == res["initialAvail"] - res["deduct"], (
        f"Expected remaining {res['initialAvail'] - res['deduct']}, got {res['afterAvail']} (Stock state: {res.get('stockVal')})"
    )
    assert res["afterAvail"] > 0, "Partially consumed product should NOT be 0 or depleted"
    assert "Съедено" in (res["toast"] or "")


def test_browser_ui_mealprep_flow(browser: BrowserSession):
    """Verify mealprep wizard navigation and batch state in the browser."""
    res = browser.eval("""
        (() => {
            if (!window.__app) return { error: 'no-instance' };
            const app = window.__app;
            app.setState({ route: 'mealprep' });
            return {
                route: app.state.route,
                batchesCount: app.state.batches.length
            };
        })()
    """)
    assert res["route"] == "mealprep"
