class logger {
    string module;
    int level;
}

logger@ new_logger(string module, int level) {
    logger l;
    l.module = module;
    l.level = level;
    return l;
}

void log(logger@ l, int log_level, const string &in line)
{
	if (log_level > l.level)
	{
		return;
	}

	print("[" + l.module + "] " + line + "\n");
}
void log_error(logger@ l, const string &in text)
{
	log(l, 0, "[err] " + text);
}
void log_warning(logger@ l, const string &in text)
{
	log(l, 1, "[warn] " + text);
}
void log_info(logger@ l, const string &in text)
{
	log(l, 2, "[info] " + text);
}
void log_debug(logger@ l, const string &in text)
{
	log(l, 3, "[dbg] " + text);
}
void log_trace(logger@ l, const string &in text)
{
	log(l, 4, "[trc] " + text);
}