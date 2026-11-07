"""USB preparation feedback on desktop/mobile; simulated events only."""
from playwright.sync_api import sync_playwright
from ui_smoke import BRIDGE, fixture_context, settle


def main():
    bridge = BRIDGE.replace('window.__emitFixture=(change)=>{', '''
window.__noticeFixture=(code)=>callbacks.get(window.__fixture.event)?.({event:'backend',id:1,payload:{type:'notice',data:{code}}});
window.__emitFixture=(change)=>{''')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for lang, loading, success, failure in (
            ('zh', '正在准备有线 USB 连接', 'USB 连接已恢复', 'USB 连接准备失败'),
            ('en', 'Preparing wired USB connection', 'USB connection restored', 'USB connection preparation failed')):
            for width in (800, 360):
                context = fixture_context(browser, viewport={'width': width, 'height': 740})
                context.add_init_script(bridge + "localStorage.setItem('language','"+lang+"');localStorage.setItem('onboarding-v1','seen');")
                page = context.new_page()
                page.goto('http://127.0.0.1:1420')
                settle(page)
                page.evaluate("window.__noticeFixture('usb_preparing')")
                page.get_by_text(loading, exact=True).wait_for()
                assert page.locator('[data-sonner-toast][data-type=loading]').count() == 1
                page.evaluate("window.__noticeFixture('usb_ready')")
                page.get_by_text(success, exact=True).wait_for()
                assert page.locator('[data-sonner-toast]').count() == 1
                assert page.locator('[data-sonner-toast][data-type=success]').count() == 1
                page.evaluate("window.__noticeFixture('usb_preparing')")
                page.get_by_text(loading, exact=True).wait_for()
                page.evaluate("window.__noticeFixture('usb_prepare_failed')")
                page.get_by_text(failure, exact=True).wait_for()
                assert page.locator('[data-sonner-toast]').count() == 1
                assert page.locator('[data-sonner-toast][data-type=error]').count() == 1
                context.close()
        browser.close()
    print('USB preparation: Chinese/English, desktop/mobile, loading replaced by success/failure')


if __name__ == '__main__':
    main()
