package cn.kanokano.openwrt.mobile

import org.junit.Assert.*
import org.junit.Test

class TaskWorkStateTest {
    @Test fun installUpdateAndRemovalKeepProtectionAfterStartRequestReturns() {
        for (operation in listOf("install", "update", "uninstall")) {
            val events = mutableListOf<Pair<Boolean, Boolean>>()
            val work = TaskWorkState { active, local -> events.add(active to local) }
            val request = work.begin(false)
            work.backend(true)
            work.end(request)
            assertTrue(operation, work.active())
            assertEquals(listOf(true to false), events)
            // No UI listener is needed for worker cleanup to release protection.
            work.backend(false)
            assertFalse(operation, work.active())
            assertEquals(listOf(true to false, false to true), events)
        }
    }
    @Test fun quickWorkerCompletionStillProtectsPendingExportAndRequestCleanup() {
        val work = TaskWorkState { _, _ -> }
        val request = work.begin(false)
        work.backend(true)
        work.backend(false)
        assertTrue(work.active())
        work.end(request)
        assertFalse(work.active())
    }
    @Test fun nestedLocalJobsAndDeviceWorkReleaseOnlyTheirOwnLeases() {
        val events = mutableListOf<Pair<Boolean, Boolean>>()
        val work = TaskWorkState { active, local -> events.add(active to local) }
        val importJob = work.begin(true)
        val plan = work.begin(false)
        val export = work.begin(true)
        work.end(plan)
        assertTrue(work.active())
        work.end(importJob)
        work.end(importJob) // Duplicate completion cannot release export.
        assertTrue(work.active())
        work.end(export)
        assertEquals(listOf(true to true, true to false, true to true, false to true), events)
    }
    @Test fun failedSynchronousJobReleasesAndNextJobCanStart() {
        val work = TaskWorkState { _, _ -> }
        val request = work.begin(true)
        try { error("analysis failed") } catch (_: IllegalStateException) { }
        finally { work.end(request) }
        assertFalse(work.active())
        val next = work.begin(false)
        work.end(request) // An old callback must not finish the new request.
        assertTrue(work.active())
        work.end(next)
        assertFalse(work.active())
    }
    @Test fun serviceStartFailureDoesNotLeaveAStaleLease() {
        var reject = true
        val work = TaskWorkState { _, _ -> if (reject) error("foreground start rejected") }
        try { work.begin(false); fail("expected rejection") } catch (_: IllegalStateException) { }
        assertFalse(work.active())
        reject = false
        val token = work.begin(false)
        work.end(token)
        assertFalse(work.active())
    }
    @Test fun workerEndDoesNotReleaseAnotherConcurrentRequest() {
        val work = TaskWorkState { _, _ -> }
        work.backend(true)
        val requests = (1..16).map { work.begin(it % 2 == 0) }
        val threads = requests.dropLast(1).map { token -> Thread { work.end(token) }.apply { start() } }
        Thread { work.backend(false) }.apply { start(); join() }
        threads.forEach { it.join() }
        assertTrue(work.active())
        work.end(requests.last())
        assertFalse(work.active())
    }
}
