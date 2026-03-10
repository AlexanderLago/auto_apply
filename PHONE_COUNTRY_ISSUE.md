# Phone Country Widget Issue - For Claude Code

## Problem Summary
The phone country dropdown (iti widget) is NOT being selected, causing form submission to fail with "Select a country" validation error.

## What Works
✅ All 9-11 EEO dropdowns fill correctly
✅ Resume uploads work
✅ Cover letter uploads work
✅ Personal info (name, email, phone number) fills correctly
✅ Submit button clicking works
✅ Validation error detection works

## What's Broken
❌ Phone country dropdown selection fails
❌ Forms fail validation with "select a country" error
❌ No successful submissions yet

## Evidence from Logs

```
2026-03-09 14:23:51,472 | WARNING | Could not set phone country — form may show 'Select a country' error
2026-03-09 14:23:51,739 | INFO | Phone filled
...
2026-03-09 14:25:54,302 | ERROR | [VALIDATION ERROR] Form has 1 errors: ['select a country']
```

## Screenshot Evidence
See: `logs/screenshots/submission_*.png`
- Shows "Country" field in red with "Select a country" error
- Phone number IS filled correctly: "(722) 642-7591"
- Country dropdown shows empty/default state

## Technical Details

### Widget Type
Greenhouse uses the **iti (International Telephone Input)** widget:
- GitHub: https://github.com/jackocnr/intl-tel-input
- The widget has a country button with class `.iti__selected-flag`
- Clicking opens a dropdown with country options
- Options have class `.iti__country` with data attributes like `data-country-code="US"`

### What We've Tried

1. **Standard select_option()** - Doesn't work, not a standard `<select>`
2. **Clicking .iti__selected-flag** - Opens dropdown but selection doesn't register
3. **JavaScript evaluation** - Can find elements but clicks don't register
4. **Mouse clicks at calculated positions** - Opens dropdown but selection fails
5. **Waiting for dropdown** - Added delays but still fails

### Current Code (easy_apply.py lines ~759-840)
```python
# Method 1: Try standard select by label
country_select = page.get_by_label("Country")
if country_select.count() > 0:
    country_select.select_option("US")  # Doesn't work - not a select

# Method 2: Try iti widget selectors
country_btn = page.locator('.iti__selected-flag').first
if country_btn.count() > 0:
    country_btn.click()  # Opens dropdown
    page.wait_for_timeout(500)
    us_option = page.locator('[class*="iti__country"]').filter(has_text="United States").first
    if us_option.count() > 0:
        us_option.click()  # Click doesn't register!

# Method 3: JavaScript
result = page.evaluate("""() => {
    const countryBtn = document.querySelector('.iti__selected-flag');
    if (countryBtn) {
        countryBtn.click();
        return 'clicked';
    }
    return 'not found';
}""")  # Clicks but selection doesn't work
```

## Hypotheses

1. **React state not updating** - The iti widget might use React state and our clicks don't trigger the state update
2. **Event listener issue** - The widget might use specific event types (mousedown/mouseup) that we're not triggering correctly
3. **Timing issue** - The dropdown might need more time to initialize before selection
4. **Shadow DOM** - The widget might be in a shadow DOM (unlikely but possible)

## Suggested Approaches for Claude Code

### Approach A: Analyze Widget Events
1. Use browser devtools to inspect what events the iti widget listens for
2. Try triggering those specific events via JavaScript:
   ```javascript
   const btn = document.querySelector('.iti__selected-flag');
   btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
   btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
   ```

### Approach B: Direct Widget API
The iti widget has a JavaScript API:
```javascript
const input = document.querySelector('#phone');
const iti = window.intlTelInputGlobals.getInstance(input);
iti.setCountry('us');
```
Try accessing this API via page.evaluate()

### Approach C: Alternative Selectors
The widget structure might have changed. Try:
- `[aria-label*="country"]`
- `[title*="United States"]`
- `button[aria-expanded]` near the phone field

### Approach D: Force Form Submission
If country selection proves impossible:
1. Try submitting anyway and see if there's a way to bypass
2. Check if the form has a hidden country input we can set directly

## Files to Examine
- `modules/applicator/easy_apply.py` - Lines 759-840 (phone country logic)
- `logs/screenshots/submission_*.png` - Shows the widget state

## Test Command
```bash
cd auto_apply
python main.py apply --limit 1 --submit
```

## Success Criteria
- Phone country dropdown selects "United States" successfully
- Form submits without "select a country" error
- At least one confirmed successful application

## Companies to Test On
Priority (known working forms besides phone country):
1. GitLab
2. Stripe
3. Discord
4. Gusto

SKIP (broken forms):
- Amplitude (scrambled EEO dropdowns)
- Chime (scrambled EEO dropdowns)
