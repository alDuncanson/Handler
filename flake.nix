{
  description = "Handler - An A2A Protocol client TUI and CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python313;
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.uv
            pkgs.just
            pkgs.ruff
            pkgs.ty
          ];

          env = {
            # Keep uv in sync with the Nix-provided Python.
            UV_PYTHON = "${python}/bin/python3";
          };

          shellHook = ''
            echo ""
            echo "  _                     _ _           "
            echo " | |__   __ _ _ __   __| | | ___ _ __ "
            echo " | '_ \\ / _\` | '_ \\ / _\` | |/ _ \\ '__|"
            echo " | | | | (_| | | | | (_| | |  __/ |   "
            echo " |_| |_|\\__,_|_| |_|\\__,_|_|\\___|_|   "
            echo ""
            echo "A2A Protocol client TUI and CLI"
            echo ""
            echo "Commands:"
            echo "  just install    Install dependencies"
            echo "  just check      Run lint, format, and typecheck"
            echo "  just test       Run tests"
            echo "  just run        Run handler"
            echo ""
            echo "Run 'just' to see all available commands."
            echo ""
          '';
        };
      }
    );
}
