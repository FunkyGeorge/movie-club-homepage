{
  description = "movie-club development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      eachSystem = nixpkgs.lib.genAttrs systems;
    in {
      devShells = eachSystem (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = with pkgs; [
              python312
              uv
              postgresql_16
              gnumake
              git
              curl
              jq
              ruff
            ];

            # Shared libraries needed by the pandas/matplotlib wheels.
            buildInputs = with pkgs; [
              stdenv.cc.cc.lib
              zlib
            ];

            env = {
              # Use the Nix Python instead of downloading uv's own interpreter.
              UV_PYTHON_DOWNLOADS = "never";
              # Make the C++ runtime available to the pandas/matplotlib wheels.
              LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
                pkgs.stdenv.cc.cc.lib
                pkgs.zlib
              ];
            };

            shellHook = ''
              echo "movie-club dev shell"
              echo "python: $(python3.12 --version)"
            '';
          };
        });
    };
}
