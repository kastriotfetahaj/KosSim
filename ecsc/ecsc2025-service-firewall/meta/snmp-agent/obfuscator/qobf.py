#!/usr/bin/env python3
import argparse
import os
import pathlib

from elftools.elf.elffile import ELFFile

def obfuscate(path: pathlib.Path, section_name: str):
    with path.open('r+b') as obj:
        elf = ELFFile(obj)
        section = elf.get_section_by_name(section_name)
        if section is None:
            return
        offset = section['sh_offset']
        size = section['sh_size']

        obj.seek(offset, os.SEEK_SET)
        data = bytearray(obj.read(size))

        for index, byte in enumerate(data):
            byte = ((byte << 5) | (byte >> 3)) & 0xff
            byte = (byte * pow(37, -1, 256)) & 0xff
            byte = ((byte << 5) | (byte >> 3)) & 0xff
            byte = (byte * pow(13, -1, 256)) & 0xff
            byte = ((byte << 5) | (byte >> 3)) & 0xff
            data[index] = byte

        obj.seek(offset, os.SEEK_SET)
        obj.write(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-j', '--section', help='Target section', type=str, default='.rodata.hidden')
    parser.add_argument('objfile', help='Object file to modify', type=pathlib.Path)
    args = parser.parse_args()
    obfuscate(args.objfile, args.section)

