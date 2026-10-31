"""Read-only Codex subscription power. Never infer usage or spend/reset credits."""
import copy
import datetime
import math
import threading
import time


def window_label(minutes):
    if minutes % 1440 == 0: return str(minutes // 1440) + '天电量'
    if minutes % 60 == 0: return str(minutes // 60) + '小时电量'
    return str(minutes) + '分钟电量'


def local_time(value, timespec='minutes'):
    try:
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).astimezone().isoformat(timespec=timespec)
    except (ValueError, OverflowError, OSError, TypeError): return '未知'


def normalize(payload):
    """Allowlist public usage fields; exclude account IDs, credits and identity."""
    if not isinstance(payload, dict): raise ValueError('未返回有效电量数据。')
    source = payload.get('rateLimitsByLimitId')
    source = dict(source) if isinstance(source, dict) else {}
    legacy = payload.get('rateLimits')
    if isinstance(legacy, dict):
        source.setdefault(legacy.get('limitId') or 'codex', legacy)
    buckets = []
    for key, bucket in source.items():
        if not isinstance(key, str) or not isinstance(bucket, dict): continue
        windows = []
        for kind in ('primary', 'secondary'):
            window = bucket.get(kind)
            if not isinstance(window, dict): continue
            used = window.get('usedPercent'); minutes = window.get('windowDurationMins')
            if (type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100
                or type(minutes) is not int or not 0 < minutes <= 525600): continue
            reset = window.get('resetsAt')
            if type(reset) not in (int, float) or not math.isfinite(reset) or reset <= 0: reset = None
            windows.append(dict(kind=kind, label=window_label(minutes), minutes=minutes,
                                remainingPercent=round(100-used, 2), resetsAt=reset))
        if windows:
            name = bucket.get('limitName')
            buckets.append(dict(id=key[:120], name=(name[:120] if isinstance(name, str) and name else ('Codex' if key == 'codex' else key[:120])),
                                windows=windows, blocked=bucket.get('spendControlReached') is True))
    if not buckets: raise ValueError('服务端没有提供可用的订阅电量。')
    return dict(buckets=buckets, ordinaryUsageAllowed=payload.get('ordinaryUsageAllowed') if type(payload.get('ordinaryUsageAllowed')) is bool else None)


class PowerMonitor:
    def __init__(self, reader, clock=time.time, interval=60, stale_after=180):
        self.reader=reader; self.clock=clock; self.interval=interval; self.stale_after=stale_after
        self.lock=threading.RLock(); self.stop=threading.Event(); self.wake=threading.Event()
        self.thread=None; self.data=None; self.updated_at=None; self.error=''; self.loading=False
        self.version=0; self.next_manual=0

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start()

    def accept(self, payload, expected_version=None):
        data=normalize(payload)
        with self.lock:
            if expected_version is not None and expected_version != self.version: return False
            self.data=data; self.updated_at=self.clock(); self.error=''; self.version+=1
        return True

    def refresh(self):
        with self.lock:
            if self.loading: return
            self.loading=True; version=self.version
        try: self.accept(self.reader(), expected_version=version)
        except Exception:
            # Exceptions from the account process can contain private account details.
            with self.lock:
                if version == self.version: self.error='暂时读不到订阅电量，请稍后刷新。'
        finally:
            with self.lock: self.loading=False

    def request(self):
        with self.lock:
            if self.loading or self.clock() < self.next_manual: return
            self.next_manual=self.clock()+15
        self.wake.set()

    def run(self):
        while not self.stop.is_set():
            self.refresh()
            self.wake.wait(self.interval); self.wake.clear()

    def snapshot(self):
        with self.lock:
            data=copy.deepcopy(self.data); updated=self.updated_at; error=self.error; loading=self.loading
        now=self.clock()
        if not data:
            return dict(status='unknown', buckets=[], updatedAt=None, loading=loading,
                        error=error, level='unknown', remainingPercent=None)
        stale=bool(error) or now-updated > self.stale_after
        for bucket in data['buckets']:
            for window in bucket['windows']:
                window['stale']=stale or bool(window['resetsAt'] and window['resetsAt'] <= now)
        main=next((b for b in data['buckets'] if b['id']=='codex'),None)
        if main is None and len(data['buckets'])==1: main=data['buckets'][0]
        fresh_main=main and all(not w['stale'] for w in main['windows'])
        remaining=min(w['remainingPercent'] for w in main['windows']) if fresh_main else None
        blocked=data['ordinaryUsageAllowed'] is False or bool(main and main['blocked'])
        level='unknown' if remaining is None else 'empty' if remaining==0 or blocked else 'critical' if remaining<=5 else 'low' if remaining<=20 else 'normal'
        return dict(**data, status='stale' if stale or any(w['stale'] for b in data['buckets'] for w in b['windows']) else 'ok',
                    updatedAt=updated, loading=loading, error=error, level=level, remainingPercent=remaining,
                    blocked=blocked, mainBucket=main['id'] if main else None)

    def prompt(self):
        state=self.snapshot()
        if state['updatedAt'] is None: return '\nGPT电量：暂未读取成功，余量未知；不要推测。\n'
        lines=['\nGPT订阅电量（官方用量接口，非电脑电池；调用前读数）：']
        for bucket in state['buckets']:
            for window in bucket['windows']:
                reset=local_time(window['resetsAt']) if window['resetsAt'] else '未知'
                lines.append(f"{bucket['name']} · {window['label']}剩余{window['remainingPercent']:g}%，恢复时间{reset}"+('（上次读数，当前待更新）' if window['stale'] else ''))
        lines.append('读取时间：'+local_time(state['updatedAt'],timespec='seconds'))
        if state['level'] in ('low','critical','empty') or state['blocked']:
            lines.append('低电量分工提醒：人类希望DeepSeek主动接手适合的实现、调研和整理，Codex尽量交接已有进展并减少重复工作；同一任务先认领再操作，避免两人同时改同一文件。分担不扩大授权、不公开私人对话。')
        if state['status'] != 'ok': lines.append('数据不是实时确认，不能据此认定已经恢复；不要虚报满电。')
        lines.append('余量不代表还能回答的确切条数；这里只读，不购买点数、不消耗重置券、不自动切换模型。')
        return '\n'.join(lines)+'\n'

    def close(self):
        self.stop.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=1)
