# Implementation Tasks

## 1. Core Implementation
- [ ] 1.1 Add `fails_successfully(response: Response) -> bool` method to `BaseScraper` (returns `True`)
- [ ] 1.2 Update `SyncDriver` to call `fails_successfully()` for SpeculativeRequest responses, set status_code=555 if False
- [ ] 1.3 Update `AsyncDriver` with same logic
- [ ] 1.4 Verify `LocalDevDriver` behavior (inherits from AsyncDriver)

## 2. Testing
- [ ] 2.1 Add unit test for `fails_successfully()` default behavior
- [ ] 2.2 Add test with mock scraper that overrides `fails_successfully()` returning False
- [ ] 2.3 Verify status code is set to 555 before `on_speculation_response` is called
