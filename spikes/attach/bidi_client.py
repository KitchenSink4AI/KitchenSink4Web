"""A thin in-house WebDriver BiDi client, written from the W3C spec.

This is the Lane C thesis made concrete: Playwright has no connectOverBiDi, so
attaching to a user-launched Firefox (--remote-debugging-port) requires exactly
this — a WebSocket plus JSON commands per https://w3c.github.io/webdriver-bidi/.

Written from the spec, not lifted from Playwright's bidi sources (DESIGN 4.4,
license hygiene). Command/response correlation is by integer id; events that
arrive while awaiting a response are stashed in self.events.
"""
import asyncio
import json

import websockets


class BidiError(Exception):
    def __init__(self, payload):
        self.payload = payload
        super().__init__("%s: %s" % (payload.get("error"), payload.get("message")))


class BidiClient:
    def __init__(self, port, host="127.0.0.1"):
        self.url = "ws://%s:%d/session" % (host, port)
        self.ws = None
        self._id = 0
        self.events = []          # every event frame seen, in arrival order
        self.session_id = None

    async def connect(self, timeout=15.0):
        self.ws = await asyncio.wait_for(
            websockets.connect(self.url, max_size=1 << 26), timeout)

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def send(self, method, params=None, timeout=30.0):
        """Send one command; return its success result. Raises BidiError on an
        error response. Event frames received meanwhile are stashed."""
        self._id += 1
        cid = self._id
        await self.ws.send(json.dumps(
            {"id": cid, "method": method, "params": params or {}}))
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError("no response to %s (id %d)" % (method, cid))
            frame = json.loads(await asyncio.wait_for(self.ws.recv(), remaining))
            if frame.get("id") == cid:
                if frame.get("type") == "success":
                    return frame.get("result", {})
                raise BidiError(frame)
            if frame.get("type") == "event":
                self.events.append(frame)
            # responses to other ids should not happen in this single-flight
            # client; if one arrives, stash it as an anomaly
            elif frame.get("id") is not None:
                self.events.append({"anomaly": frame})

    # -- convenience wrappers, spec module.command names throughout --

    async def session_new(self):
        r = await self.send("session.new", {"capabilities": {}})
        self.session_id = r.get("sessionId")
        return r

    async def get_tree(self):
        return await self.send("browsingContext.getTree", {})

    async def navigate(self, context, url, wait="complete", timeout=45.0):
        return await self.send("browsingContext.navigate",
                               {"context": context, "url": url, "wait": wait},
                               timeout=timeout)

    async def evaluate(self, context, expression, await_promise=False):
        r = await self.send("script.evaluate", {
            "expression": expression,
            "target": {"context": context},
            "awaitPromise": await_promise,
            "resultOwnership": "none",
        })
        if r.get("type") == "exception":
            raise BidiError({"error": "script exception",
                             "message": json.dumps(r.get("exceptionDetails", {}))[:400]})
        return r.get("result", {})

    async def screenshot(self, context):
        return await self.send("browsingContext.captureScreenshot",
                               {"context": context})

    async def click_at(self, context, x, y):
        return await self.send("input.performActions", {
            "context": context,
            "actions": [{
                "type": "pointer", "id": "mouse",
                "parameters": {"pointerType": "mouse"},
                "actions": [
                    {"type": "pointerMove", "x": int(x), "y": int(y), "duration": 0},
                    {"type": "pointerDown", "button": 0},
                    {"type": "pointerUp", "button": 0},
                ],
            }],
        })

    async def traverse_history(self, context, delta, timeout=15.0):
        return await self.send("browsingContext.traverseHistory",
                               {"context": context, "delta": delta}, timeout=timeout)

    async def session_end(self):
        return await self.send("session.end", {})
