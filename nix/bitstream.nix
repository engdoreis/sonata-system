{
  pkgs,
  lrItPkgs,
  pythonEnv,
}: {
  build = pkgs.writeShellApplication {
    name = "build";
    runtimeInputs = [pythonEnv lrItPkgs.vivado];
    text = ''
      fusesoc --cores-root=. run --target=synth --setup --build lowrisc:sonata:system \
      --SRAMInitFile=sw/cheri/build/tests/uart_check.vmem
    '';
  };

  load = pkgs.writeShellApplication {
    name = "load";
    runtimeInputs = [pythonEnv lrItPkgs.vivado];
    text = ''
      openFPGALoader -c ft4232 ./build/lowrisc_ibex_sonata_0/synth-vivado/lowrisc_ibex_sonata_0.bit
    '';
  };
}
