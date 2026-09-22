"""At-least-once outbox worker with deterministic idempotency keys and dead letters."""
class OutboxWorker:
    def __init__(self,metadata_store,handler,max_attempts=3):
        self.meta=metadata_store; self.handler=handler; self.max_attempts=max_attempts
    def drain_once(self,limit=100,crash_after_handler=False):
        results=[]
        for event in self.meta.pending_outbox(limit):
            if self.meta.event_processed(event.idempotency_key):
                self.meta.mark_event_done(event); results.append((event.event_id,"deduplicated")); continue
            try:
                self.handler(event,event.idempotency_key)
                if crash_after_handler: raise SystemExit("simulated crash after handler before outbox ack")
                self.meta.mark_event_done(event); results.append((event.event_id,"done"))
            except SystemExit: raise
            except Exception as exc:
                self.meta.fail_event(event,str(exc),self.max_attempts); results.append((event.event_id,"failed"))
        return tuple(results)
