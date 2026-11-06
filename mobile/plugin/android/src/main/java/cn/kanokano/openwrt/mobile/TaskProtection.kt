package cn.kanokano.openwrt.mobile

import android.app.Activity
import android.app.Application
import android.content.Context
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import java.lang.ref.WeakReference

/** CPU protection belongs to the service; display protection follows the visible Activity. */
internal object TaskProtection : Application.ActivityLifecycleCallbacks {
    private lateinit var context: Context
    private var registered = false
    private var screen = WeakReference<Activity>(null)
    private val main = Handler(Looper.getMainLooper())
    private val work = TaskWorkState { active, local ->
        if (active) InstallerTaskService.beginTask(context, local)
        else InstallerTaskService.finishTask(context)
        // Read current state when executed, so an old queued completion cannot
        // clear the display flag of a newer task.
        main.post { updateScreen() }
    }
    fun attach(activity: Activity) {
        check(Looper.myLooper() == Looper.getMainLooper())
        if (!registered) {
            context = activity.applicationContext
            (context as Application).registerActivityLifecycleCallbacks(this)
            registered = true
        }
        if (screen.get() !== activity) {
            screen.get()?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            screen = WeakReference(activity)
        }
        updateScreen()
    }
    private fun updateScreen() {
        val activity = screen.get() ?: return
        if (activity.isDestroyed) return
        if (work.active()) activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
    fun begin(local: Boolean): Long = work.begin(local)
    fun end(token: Long) = work.end(token)
    fun backend(active: Boolean) = work.backend(active)
    override fun onActivityResumed(activity: Activity) = attach(activity)
    override fun onActivityDestroyed(activity: Activity) {
        if (screen.get() === activity) screen.clear()
    }
    override fun onActivityCreated(activity: Activity, state: Bundle?) {}
    override fun onActivityStarted(activity: Activity) {}
    override fun onActivityPaused(activity: Activity) {}
    override fun onActivityStopped(activity: Activity) {}
    override fun onActivitySaveInstanceState(activity: Activity, state: Bundle) {}
}
