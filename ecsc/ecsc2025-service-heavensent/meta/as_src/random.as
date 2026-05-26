file dev_random;

void rand_init()
{
	int r = dev_random.open("/dev/random", "r");
	assert(r >= 0, "failed to open /dev/random");
}

uint64 rand_u64()
{
	return dev_random.readUInt(8);
}