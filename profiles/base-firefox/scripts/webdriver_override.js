// Override navigator.webdriver to false.
//
// Firefox's Marionette protocol (required by Playwright) always sets
// navigator.webdriver = true.  This script runs via addInitScript()
// before any page JavaScript, so Cloudflare's check sees false.
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
});
