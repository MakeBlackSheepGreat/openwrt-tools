package cn.kanokano.openwrt.mobile

/** Process-owned leases: finishing a request must not finish its async worker. */
internal class TaskWorkState(private val changed: (active: Boolean, local: Boolean) -> Unit) {
    private val requests = mutableMapOf<Long, Boolean>()
    private var next = 0L
    private var backend = false
    private var published = false to true
    @Synchronized fun begin(local: Boolean): Long {
        val token = ++next
        requests[token] = local
        try { publish() } catch (error: Exception) { requests.remove(token); throw error }
        return token
    }
    @Synchronized fun end(token: Long) { requests.remove(token); publish() }
    @Synchronized fun backend(active: Boolean) { backend = active; publish() }
    @Synchronized fun active(): Boolean = backend || requests.isNotEmpty()
    private fun publish() {
        val state = active() to (!backend && requests.values.all { it })
        if (state != published) {
            changed(state.first, state.second)
            published = state
        }
    }
}
