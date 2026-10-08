"""Versioned local adapter for future integrations; never opens a network port."""
import time

import control_actions as actions
from item_journal import Journal
from live_feed import LiveFeed
from status_view import snapshot

API_VERSION = 1
COMMANDS = ('status', 'items', 'events', 'pause', 'resume', 'stop')


def dispatch(command, request_id=None, limit=50):
    """Return (JSON envelope, exit code). Mutations use the existing input guards."""
    response = {'api_version': API_VERSION, 'ok': False, 'command': command,
                'request_id': request_id, 'at': time.time(), 'data': None, 'error': None}
    if command not in COMMANDS or not isinstance(limit, int) or not 1 <= limit <= 200:
        response['error'] = {'code': 'invalid_request', 'message': 'Use a supported command and a limit from 1 to 200.'}
        return response, 2
    try:
        if command in ('pause', 'resume', 'stop'):
            message = getattr(actions, command)()
            # A successful handler is an acknowledgement, not a completed rejoin.
            result = {'message': message, 'status': snapshot()}
        else:
            journal = Journal()
            state = snapshot(journal)
            if command == 'status':
                result = state
            elif command == 'items':
                result = {'started': state['started'], 'items': [
                    {'item': name, 'quantity': quantity} for name, quantity in journal.counts.most_common()]}
            else:
                feed = LiveFeed()
                # State comes from status. Do not manufacture a new state event
                # on every poll by passing the current state to a fresh feed.
                log_run=state.get('log_run') or {}
                feed.update(log_run.get('started',state['started']),ended=log_run.get('ended'))
                rows = feed.rows[-limit:]
                result = {'started': state['started'], 'events': rows}
        response.update(ok=True, data=result)
        return response, 0
    except Exception as error:
        response['error'] = {'code': 'command_failed', 'message': str(error)}
        return response, 1
