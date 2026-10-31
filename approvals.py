"""Translate official agent approval requests; grants require an explicit UI choice."""
COMMAND = 'item/commandExecution/requestApproval'
FILE_CHANGE = 'item/fileChange/requestApproval'
PERMISSIONS = 'item/permissions/requestApproval'
ACP = 'session/request_permission'


def choices(method, params):
    if method in (COMMAND, FILE_CHANGE):
        available = params.get('availableDecisions')
        allowed = available is None or 'accept' in available
        return ([{'id': 'accept', 'label': '允许这一次'}] if allowed else []) + [
            {'id': 'decline', 'label': '拒绝'}]
    if method == PERMISSIONS:
        return [{'id': 'accept', 'label': '允许本轮所列权限'}, {'id': 'decline', 'label': '拒绝'}]
    if method == ACP:
        # Do not create permanent or session-wide grants.
        return [{'id': o['optionId'], 'label': o.get('name', '允许这一次')}
                for o in params.get('options', []) if o.get('kind') == 'allow_once'] + [
                    {'id': '__cancel__', 'label': '拒绝'}]
    return []


def response(method, params, choice):
    if method in (COMMAND, FILE_CHANGE):
        return {'decision': 'accept' if choice == 'accept' else 'decline'}
    if method == PERMISSIONS:
        return {'permissions': params.get('permissions', {}) if choice == 'accept' else {}, 'scope': 'turn'}
    if method == ACP:
        valid = {o['optionId'] for o in params.get('options', []) if o.get('kind') == 'allow_once'}
        return {'outcome': {'outcome': 'selected', 'optionId': choice}} if choice in valid else {
            'outcome': {'outcome': 'cancelled'}}
    return None
