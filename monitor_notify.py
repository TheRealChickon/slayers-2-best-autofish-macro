"""Deliver an authorized error follow-up to the existing Codex chat via MCP."""
import json
import os
import subprocess


def notify(config, prompt):
    process=subprocess.Popen([config['node'],config['mcp_server']],stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,
                             encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def request(identifier,method,params):
        process.stdin.write(json.dumps({'jsonrpc':'2.0','id':identifier,'method':method,'params':params})+'\n')
        process.stdin.flush()
        while True:
            line=process.stdout.readline()
            if not line:raise RuntimeError('Codex app MCP disconnected')
            response=json.loads(line)
            if response.get('id')==identifier:
                if 'error' in response:raise RuntimeError(response['error']['message'])
                return response['result']
    try:
        request(1,'initialize',{'protocolVersion':'2024-11-05','capabilities':{},
                               'clientInfo':{'name':'autofish-error-monitor','version':'1.0'}})
        process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');process.stdin.flush()
        catalog=request(2,'tools/list',{})
        name=next(t['name'] for t in catalog['tools'] if t['name'].endswith('send_message_to_thread'))
        result=request(3,'tools/call',{'name':name,'arguments':{'threadId':config['thread_id'],'prompt':prompt},
                                      '_meta':{'openai/threadId':config['thread_id']}})
        if result.get('isError'):raise RuntimeError('Codex rejected the alert: '+str(result.get('content')))
        return result
    finally:
        process.terminate()
        try:process.wait(2)
        except subprocess.TimeoutExpired:process.kill()


def safe_notify(config,prompt,timeout=25):
    # The MCP request may wait for the desktop. Bound it in an isolated process
    # so an unavailable chat never stalls fishing or its watchdog.
    import sys
    result=subprocess.run([sys.executable,__file__],input=json.dumps({'config':config,'prompt':prompt}),
                          capture_output=True,text=True,encoding='utf-8',timeout=timeout,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError(result.stderr.strip() or 'Codex alert delivery failed')
    return json.loads(result.stdout)


if __name__=='__main__':
    import sys
    args=json.load(sys.stdin)
    print(json.dumps(notify(args['config'],args['prompt'])))
