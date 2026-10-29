import { describe, expect, it, vi } from 'vitest'

import { createRefreshCoordinator } from './refreshCoordinator'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function raceError() {
  return { response: { data: { detail: { code: 'REFRESH_RACE' } } } }
}

describe('createRefreshCoordinator', () => {
  it('collapses ten parallel calls into ONE doRefresh', async () => {
    const gate = deferred()
    const doRefresh = vi.fn(() => gate.promise)
    const coordinator = createRefreshCoordinator({ doRefresh })

    const all = Array.from({ length: 10 }, () => coordinator.refresh())
    gate.resolve('token')
    const results = await Promise.all(all)

    expect(doRefresh).toHaveBeenCalledTimes(1)
    expect(results).toEqual(Array(10).fill('token'))
  })

  it('delivers a failure to every waiter and lets the next call try again', async () => {
    const gate = deferred()
    const doRefresh = vi
      .fn()
      .mockImplementationOnce(() => gate.promise)
      .mockResolvedValue('second')

    const coordinator = createRefreshCoordinator({ doRefresh })
    const first = coordinator.refresh()
    const second = coordinator.refresh()
    gate.reject(new Error('boom'))

    await expect(first).rejects.toThrow('boom')
    await expect(second).rejects.toThrow('boom')
    expect(doRefresh).toHaveBeenCalledTimes(1)

    expect(await coordinator.refresh()).toBe('second')
    expect(doRefresh).toHaveBeenCalledTimes(2)
  })

  it('runs inside the lock wrapper and releases it after a failure', async () => {
    const calls = []
    const withLock = vi.fn(async (name, fn) => {
      calls.push(name)
      return fn()
    })
    const doRefresh = vi.fn().mockRejectedValueOnce(new Error('nope')).mockResolvedValue('ok')
    const coordinator = createRefreshCoordinator({ doRefresh, withLock })

    await expect(coordinator.refresh()).rejects.toThrow('nope')
    expect(withLock).toHaveBeenCalledTimes(1)
    expect(calls[0]).toBe('lms-refresh')

    expect(await coordinator.refresh()).toBe('ok')
    expect(withLock).toHaveBeenCalledTimes(2)
  })

  it('retries once after REFRESH_RACE and then succeeds', async () => {
    const sleep = vi.fn(() => Promise.resolve())
    const doRefresh = vi
      .fn()
      .mockRejectedValueOnce(raceError())
      .mockResolvedValue('rotated')
    const coordinator = createRefreshCoordinator({ doRefresh, sleep })

    expect(await coordinator.refresh()).toBe('rotated')
    expect(doRefresh).toHaveBeenCalledTimes(2)
    expect(sleep).toHaveBeenCalledWith(1000)
  })

  it('fails when REFRESH_RACE happens twice', async () => {
    const sleep = vi.fn(() => Promise.resolve())
    const doRefresh = vi.fn().mockRejectedValue(raceError())
    const coordinator = createRefreshCoordinator({ doRefresh, sleep })

    await expect(coordinator.refresh()).rejects.toBeTruthy()
    expect(doRefresh).toHaveBeenCalledTimes(2)
  })

  it('does not retry an ordinary error', async () => {
    const sleep = vi.fn(() => Promise.resolve())
    const doRefresh = vi.fn().mockRejectedValue(new Error('network down'))
    const coordinator = createRefreshCoordinator({ doRefresh, sleep })

    await expect(coordinator.refresh()).rejects.toThrow('network down')
    expect(doRefresh).toHaveBeenCalledTimes(1)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('runs one refresh per sequential call', async () => {
    const doRefresh = vi.fn().mockResolvedValueOnce('a').mockResolvedValueOnce('b')
    const coordinator = createRefreshCoordinator({ doRefresh })

    expect(await coordinator.refresh()).toBe('a')
    expect(await coordinator.refresh()).toBe('b')
    expect(doRefresh).toHaveBeenCalledTimes(2)
  })

  it('works when no lock helper is available', async () => {
    const doRefresh = vi.fn().mockResolvedValue('plain')
    const coordinator = createRefreshCoordinator({ doRefresh, withLock: undefined })

    expect(await coordinator.refresh()).toBe('plain')
    expect(doRefresh).toHaveBeenCalledTimes(1)
  })
})
