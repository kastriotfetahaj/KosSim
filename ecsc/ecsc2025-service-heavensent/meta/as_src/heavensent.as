#include "sdr.as"

bool exit = false;

void main()
{
    filesystem fs;

    if (!fs.isDir("/service/data/gs")) {
        fs.makeDir("/service/data/gs");
    }

    if (!fs.isDir("/service/data/op")) {
        fs.makeDir("/service/data/op");
    }

    if (!fs.isDir("/service/data/experiment")) {
        fs.makeDir("/service/data/experiment");
    }

    rand_init();
    crypto_init();
    sdr_init();
    while (!exit)
    {
        sdr_update();
        prof_frame_mark();
    }
}
