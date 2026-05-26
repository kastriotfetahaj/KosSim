import os

os.environ["CONFIG_FILE"] = basedir = (
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/config.test.json"
)
