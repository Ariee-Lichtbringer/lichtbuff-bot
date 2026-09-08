"""Per-job API leases; no Discord side effects or process-global credentials."""
import asyncio
import contextvars

_current_delivery = contextvars.ContextVar("current_queue_delivery", default=None)
_FINISH_ACTIONS = {"lichtbotResolveQueue", "lichtbotFailQueue", "lichtbotRetryQueue"}


def queue_request_params(action, params):
    delivery = _current_delivery.get()
    if delivery and action in _FINISH_ACTIONS and str(params.get("rowNumber", "")) == delivery.row:
        if str(params.get("guild", "")).lower() != delivery.guild:
            raise ValueError("Queue-Abschluss gehört zu einer anderen Gilde")
        return {**params, "leaseToken": delivery.token}
    return params


def queue_request_completed(action, params):
    delivery = _current_delivery.get()
    if not delivery:
        return
    if action in _FINISH_ACTIONS and str(params.get("rowNumber", "")) == delivery.row:
        delivery.completed = True
    elif action == "lichtbotCompletePlayerAnalysisDm" and str(params.get("guild", "")).lower() == delivery.guild:
        # This endpoint commits both the analysis receipt and its queue state.
        delivery.completed = True


class QueueDelivery:
    def __init__(self, api, guild, row, *, enabled=True, heartbeat=None, interval=60):
        self.api, self.guild, self.row = api, guild, row
        self.enabled, self.heartbeat, self.interval = enabled, heartbeat, interval
        self.token = ""
        self.acquired = not enabled
        self.completed = False
        self.lost = None
        self._watcher = None
        self._context = None

    async def __aenter__(self):
        if not self.enabled:
            return self
        result = await self.api.post("lichtbotClaimQueue", guild=self.guild,
                                     rowNumber=self.row, leaseProtocol="v1")
        if not result.get("claimed"):
            return self
        self.token = str(result.get("leaseToken") or "")
        if not self.token:
            raise RuntimeError("API muss vor dem Bot aktualisiert werden: Queue-Lease fehlt")
        self.acquired = True
        self._context = _current_delivery.set(self)
        self._owner = asyncio.current_task()
        self._watcher = asyncio.create_task(self._renew(), name="p0-queue-lease")
        return self

    async def _renew(self):
        try:
            while not self.completed:
                await asyncio.sleep(self.interval)
                if self.completed:
                    return
                result = await self.api.post("lichtbotRenewQueue", guild=self.guild,
                    rowNumber=self.row, leaseToken=self.token)
                if self.completed:
                    return
                if not result.get("renewed"):
                    raise RuntimeError("Queue-Verarbeitungssperre verloren")
                if self.heartbeat:
                    self.heartbeat()
        except Exception as error:
            if not self.completed:
                self.lost = error
                self._owner.cancel()

    async def __aexit__(self, kind, error, traceback):
        if self._watcher:
            self._watcher.cancel()
            await asyncio.gather(self._watcher, return_exceptions=True)
        if self._context is not None:
            _current_delivery.reset(self._context)
        if kind is asyncio.CancelledError and self.lost is not None:
            self._owner.uncancel()
            raise RuntimeError("Queue-Verarbeitung nach Lease-Verlust abgebrochen") from self.lost
        return False
