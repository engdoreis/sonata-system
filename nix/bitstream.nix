{
  pkgs,
  lrPkgs,
  pythonEnv,
}: {
  build = pkgs.writeShellApplication {
    name = "build";
    runtimeInputs = [pythonEnv lrPkgs.llvm_cheriot pkgs.cmake];
    text = ''
      cmake -B sw/cheri/build -S sw/cheri ;cmake --build sw/cheri/build
      fusesoc --cores-root=. run --target=synth --setup --build lowrisc:sonata:system
    '';
  };

  load = pkgs.writeShellApplication {
    name = "load";
    runtimeInputs = [pythonEnv];
    text = ''
      BITSTREAM=$(find ./ -type f -name "lowrisc_sonata_system_0.bit")
      openFPGALoader -c ft4232 "$BITSTREAM"
    '';
  };
}
