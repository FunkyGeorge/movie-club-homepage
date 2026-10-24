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

            env = {
              # Use the Nix Python instead of downloading uv's own interpreter.
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              echo "movie-club dev shell"
              echo "python: $(python3.12 --version)"
            '';
          };
        });
    };
}
