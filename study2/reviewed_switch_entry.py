"""Selected CLI admission using existing owned or reviewed empty fences.

An owned session retains real Popen handles across publish and recovery. A new
process never adopts earlier owners or interprets unknown activity as empty.
"""
import json
from pathlib import Path
import sys

from . import coordinated_update as update
from .consumer_owner_fence import OwnedConsumerFence, ScopedEmptyFence, check_guarded_runtime


def emit(value):
    print(json.dumps(value), flush=True)


def run(cfg, args):
    if args and args[0]=='reviewed-recover':
        if len(args) not in {1,3}:
            raise SystemExit('reviewed-recover takes no arguments or a recovery-scope pin file and its independent acceptance-pin file')
        journal=json.loads((Path(cfg['state_dir'])/update.JOURNAL).read_text())
        if journal.get('status')=='complete':
            emit(update.recover(cfg));return
        plan=update._load_plan(cfg,journal['plan_pin'],journal['acceptance_pin'],journal['operator'])
        check_guarded_runtime(plan)
        recovery=None if len(args)==1 else {
            'request_pin':json.loads(Path(args[1]).read_text()),
            'acceptance_pin':json.loads(Path(args[2]).read_text())}
        owner=ScopedEmptyFence(cfg,plan,recovery=recovery)
        emit(update.recover(cfg,owner_fence=owner));return
    if len(args)!=4 or args[0] not in {'reviewed-publish','reviewed-session'}:
        raise SystemExit('reviewed-publish or reviewed-session requires plan-pin file, acceptance-pin file and operator; reviewed-recover takes no arguments')
    plan_pin=json.loads(Path(args[1]).read_text());accepted=json.loads(Path(args[2]).read_text());operator=args[3]
    plan=update._load_plan(cfg,plan_pin,accepted,operator)
    check_guarded_runtime(plan)
    journal=Path(cfg['state_dir'])/update.JOURNAL
    if journal.exists():
        # Completed retries do not create children or reconstruct any lease.
        emit(update.publish(cfg,plan_pin,accepted,operator=operator));return
    if args[0]=='reviewed-publish':
        owner=ScopedEmptyFence(cfg,plan)
        emit(update.publish(cfg,plan_pin,accepted,operator=operator,owner_fence=owner));return
    owner=OwnedConsumerFence(cfg,plan)
    try:
        for name in owner.specs:owner.start(name)
        emit({'status':'owned_session_ready','owned_readers':len(owner.specs),
              'commands':['publish','recover','exit']})
        for line in sys.stdin:
            command=line.strip()
            if command=='exit':
                if journal.exists() and json.loads(journal.read_text()).get('status') in {'draining','pending'}:
                    emit({'status':'command_failed','error':'recover_pending_transition_before_exit'});continue
                return
            try:
                if command=='publish':
                    result=update.publish(cfg,plan_pin,accepted,operator=operator,owner_fence=owner)
                elif command=='recover':result=update.recover(cfg,owner_fence=owner)
                else:raise ValueError('supported_session_commands_are_publish_recover_exit')
                emit(result)
            except Exception as error:
                # Keep the actual handles available. A failed transition must
                # be explicitly recovered in this session, never republished.
                emit({'status':'command_failed','error':str(error)})
        if journal.exists() and json.loads(journal.read_text()).get('status') in {'draining','pending'}:
            raise SystemExit('Owned session input ended with a pending transition; gate remains closed and fresh processes cannot adopt its readers')
    finally:
        owner.cleanup_owned()
