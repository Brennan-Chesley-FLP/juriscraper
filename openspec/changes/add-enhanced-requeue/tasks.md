## 1. Implementation

- [ ] 1.1 Add SQL queries for finding downstream requests (recursive CTE)
- [ ] 1.2 Add SQL queries for deleting responses, results, and errors by request IDs
- [ ] 1.3 Implement `requeue_requests()` core function with clear_responses, clear_downstream, dry_run support
- [ ] 1.4 Implement `requeue_response()` helper function
- [ ] 1.5 Implement `requeue_error()` helper function with mark_resolved option
- [ ] 1.6 Implement `requeue_continuation()` helper function with error_type and traceback filtering
- [ ] 1.7 Add return type dataclass for requeue operations (RequeueResult)

## 2. Testing

- [ ] 2.1 Test requeue_requests with clear_responses=True
- [ ] 2.2 Test requeue_requests with clear_downstream=True
- [ ] 2.3 Test requeue_requests dry_run mode
- [ ] 2.4 Test requeue_error with mark_resolved=True (default) and mark_resolved=False
- [ ] 2.5 Test requeue_continuation with error_type filter
- [ ] 2.6 Test requeue_continuation with traceback_contains filter
- [ ] 2.7 Test that downstream clearing is recursive (children of children)