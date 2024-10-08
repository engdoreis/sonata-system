#!/usr/bin/env python3.10
# Copyright lowRISC contributors
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0

import subprocess
from enum import Enum
from pathlib import Path

import toml
from mako.template import Template
from pydantic import BaseModel


class BlockIoType(str, Enum):
    INOUT = "inout"
    INPUT = "input"
    OUTPUT = "output"


class BlockIoCombine(str, Enum):
    AND = "and"
    OR = "or"
    MUX = "mux"


class BlockIo(BaseModel):
    name: str
    type: BlockIoType
    combine: str | None = None
    default: int | None = None
    length: int | None = None
    pins: list[list[list[str]]] = []


class Block(BaseModel):
    name: str
    instances: int
    ios: list[BlockIo]


class PinIo(BaseModel):
    block: str
    instance: int
    io: str | int


class Pin(BaseModel):
    name: str
    length: int | None = None
    block_ios: list[PinIo]
    block_outputs: list[tuple[str, str, int, str, bool]] = []


class Config(BaseModel):
    blocks: list[Block]
    pins: list[Pin]


if __name__ == "__main__":
    toml_path = Path("data/top_config.toml")
    with toml_path.open() as file:
        config = Config(**toml.load(file))

    def get_block(name: str) -> Block:
        return next(block for block in config.blocks if block.name == name)

    def get_pin(name: str) -> Pin:
        return next(pin for pin in config.pins if pin.name == name)

    try:
        gpio = get_block("gpio")
        uart = get_block("uart")
        i2c = get_block("i2c")
        spi = get_block("spi")
    except StopIteration:
        print("One or more blocks not present in configuration.")
        exit(3)

    # Parse blocks
    block_ios = []

    for block in config.blocks:
        instances = block.instances
        for io in block.ios:
            name = block.name + "_" + io.name
            width = ""
            io_type = io.type
            length = 1
            # Generate pinmux module input and outputs
            if io.name == "ios" and io.length is not None:
                width = "[" + str(io.length - 1) + ":0] "
                length = io.length
            if io_type == BlockIoType.OUTPUT:
                block_ios.append(("input ", width, name + "_i", instances))
            elif io_type == BlockIoType.INPUT:
                block_ios.append(("output", width, name + "_o", instances))
            elif io_type == BlockIoType.INOUT:
                block_ios.append(("input ", width, name + "_i", instances))
                block_ios.append(("input ", width, name + "_en_i", instances))
                block_ios.append(("output", width, name + "_o", instances))
            io.pins = [[[] for _ in range(instances)] for _ in range(length)]

    pin_ios = []
    for pin in config.pins:
        pin_name = pin.name
        width = ""
        arrayed = False
        if pin.length is not None:
            width = "[" + str(pin.length - 1) + ":0] "
            arrayed = True
        pin_ios.append((width, pin_name))
        pin.block_outputs = []
        # Populate block parameters with which pins can connect to them.
        for bio in pin.block_ios:
            if isinstance(bio.io, int):
                bio_name = "ios"
                index = bio.io
            else:
                bio_name = bio.io
                index = 0
            for bio2 in get_block(bio.block).ios:
                if bio_name == bio2.name:
                    if arrayed and pin.length is not None:
                        for i in range(pin.length):
                            bio2.pins[index + i][bio.instance].append(pin_name)
                    else:
                        bio2.pins[index][bio.instance].append(pin_name)

    # After populating the pins field in block parameters generate input list
    # and populate outputs for pins.
    input_list = []
    combine_list = []

    for block in config.blocks:
        for io in block.ios:
            if io.type == BlockIoType.INPUT or (
                io.type == BlockIoType.INOUT
                and io.combine == BlockIoCombine.MUX
            ):
                for bit_idx, pin_list in enumerate(io.pins):
                    bit_str = "" if len(io.pins) == 1 else "_" + str(bit_idx)
                    for inst_idx, pins in enumerate(pin_list):
                        input_name = block.name + "_" + io.name
                        if io.type == BlockIoType.INOUT:
                            def_val = "1'b0"
                        else:
                            def_val = "1'b" + str(io.default)
                        input_pins = [def_val]
                        for pin_name in pins:
                            pin_with_idx = pin_name
                            pin = get_pin(pin_name)
                            if pin.length is not None:
                                if isinstance(pin.block_ios[0].io, int):
                                    pin_with_idx = (
                                        pin_name
                                        + "["
                                        + str(bit_idx - pin.block_ios[0].io)
                                        + "]"
                                    )
                                else:
                                    print("This IO must be an int.")
                                    exit()
                            input_pins.append(pin_with_idx)
                        # Make sure there are always two values in the input
                        # list because the second one is always selected by
                        # default in the RTL.
                        if len(input_pins) == 1:
                            input_pins.append(def_val)
                        input_list.append(
                            (
                                input_name,
                                inst_idx,
                                bit_idx,
                                bit_str,
                                input_pins,
                            )
                        )
            if io.type == BlockIoType.OUTPUT or io.type == BlockIoType.INOUT:
                for bit_idx, pin_list in enumerate(io.pins):
                    if len(io.pins) == 1:
                        bit_str = ""
                    else:
                        bit_str = "[" + str(bit_idx) + "]"
                    for inst_idx, pins in enumerate(pin_list):
                        for pin_name in pins:
                            pin = get_pin(pin_name)
                            pin.block_outputs.append(
                                (
                                    block.name,
                                    io.name,
                                    inst_idx,
                                    bit_str,
                                    io.type == BlockIoType.INOUT,
                                )
                            )
    for block in config.blocks:
        for io in block.ios:
            if (
                io.type == BlockIoType.INOUT
                and io.combine != BlockIoCombine.MUX
            ):
                if len(io.pins) != 1:
                    print(
                        "Currently we don't support indexing inout "
                        + "signals that are combined through muxing."
                    )
                    exit()
                for inst_idx, pins in enumerate(io.pins[0]):
                    input_name = block.name + "_" + io.name
                    combine_pins = pins
                    combine_pin_selectors = []
                    for pin_name in combine_pins:
                        pin = get_pin(pin_name)
                        for sel_idx, block_output in enumerate(
                            pin.block_outputs
                        ):
                            if block_output[3] != "":
                                print(
                                    "Combining indexed pins is currently "
                                    + "unsupported."
                                )
                                exit()
                            if block_output[0] is block.name and (
                                block_output[1] is io.name
                                and block_output[2] is inst_idx
                            ):
                                combine_pin_selectors.append(
                                    1 << (sel_idx + 1)
                                )
                                break
                    if len(combine_pins) != len(combine_pin_selectors):
                        print("Could not fill combine pin selectors properly.")
                        exit()
                    combine_list.append(
                        (
                            input_name,
                            inst_idx,
                            combine_pins,
                            combine_pin_selectors,
                            io.combine,
                        )
                    )

    output_list: list[
        tuple[str, str, str, list[tuple[str, str, int, str, bool]]]
    ] = []

    for pin in config.pins:
        outputs = pin.block_outputs
        if outputs != []:
            if pin.length is not None:
                if pin.length != len(outputs):
                    print(
                        "Arrayed pin must have complete mapping: " + pin.name
                    )
                    exit()
                output_list.extend(
                    (pin.name, "_" + str(i), "[" + str(i) + "]", [outputs[i]])
                    for i in range(pin.length)
                )
            else:
                output_list.append((pin.name, "", "", outputs))

    # Then we use those parameters to generate our SystemVerilog using Mako
    xbar_spec = ("data/xbar_main.hjson", "data/xbar_main_generated.hjson")
    sonata_xbar_spec = (
        "rtl/templates/sonata_xbar_main.sv.tpl",
        "rtl/bus/sonata_xbar_main.sv",
    )
    pkg_spec = ("rtl/templates/sonata_pkg.sv.tpl", "rtl/system/sonata_pkg.sv")
    pinmux_spec = ("rtl/templates/pinmux.sv.tpl", "rtl/system/pinmux.sv")
    pinmux_doc_spec = ("doc/ip/pinmux.md.tpl", "doc/ip/pinmux.md")

    specs = [
        xbar_spec,
        sonata_xbar_spec,
        pkg_spec,
        pinmux_spec,
        pinmux_doc_spec,
    ]

    for template_file, output_file in specs:
        print("Generating from template: " + template_file)
        template = Template(filename=template_file)
        content = template.render(
            gpio_num=gpio.instances,
            uart_num=uart.instances,
            i2c_num=i2c.instances,
            spi_num=spi.instances,
            block_ios=block_ios,
            pin_ios=pin_ios,
            input_list=input_list,
            output_list=output_list,
            combine_list=combine_list,
        )
        generated_file = Path(output_file)
        generated_file.write_text(content)

    subprocess.call(["sh", "util/generate_xbar.sh"])
