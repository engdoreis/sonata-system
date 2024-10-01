{
  pkgs,
  pythonEnv,
  sonataSimulatorFileset,
  ...
}: let
  inherit (pkgs.lib) fileset getExe;

  lint-python = pkgs.writeShellApplication {
    name = "lint-python";
    runtimeInputs = [pythonEnv];
    text = ''
      ruff format --check .
      ruff check .
      mypy .
    '';
  };

  lint-cpp = pkgs.writeShellApplication {
    name = "lint-cpp";
    runtimeInputs = [pkgs.clang-tools_18];
    text = ''
      set +u
      EXCLUDE="sw/cheri/build"
      FILES=$(find sw -type f -path "$EXCLUDE" -prune -o \( -name "*.c" -o -name "*.cc" -o -name "*.h" -o -name "*.hh" \))
      ARG="$1"
      [ -z "$1" ] && ARG="check"
      case "$ARG" in
        check)
          echo "$FILES" | xargs clang-format -n --Werror
        ;;
        fix)
          echo "$FILES" | xargs clang-format -i
        ;;
      esac
    '';
  };

  lint-sonata-simulator = pkgs.stdenvNoCC.mkDerivation {
    name = "sonta-simulator-lint";
    src = sonataSimulatorFileset;
    buildInputs = with pkgs; [libelf zlib];
    nativeBuildInputs = [pkgs.verilator pythonEnv];
    dontBuild = true;
    doCheck = true;
    checkPhase = ''
      HOME=$TMPDIR fusesoc --cores-root=. run \
        --target=lint --setup --build lowrisc:sonata:system \
        --verilator_options="+define+RVFI -j $NIX_BUILD_CORES"
    '';
    installPhase = "mkdir $out";
  };
in {
  all = pkgs.writers.writeBashBin "lint-all" ''
    set -e
    ${getExe pkgs.reuse} --suppress-deprecation lint
    ${getExe pkgs.lychee} --offline --no-progress .
    ${getExe lint-python}
    ${getExe lint-cpp}
  '';
  python = lint-python;
  cpp = lint-cpp;
  sonata-simulator = lint-sonata-simulator;
}
