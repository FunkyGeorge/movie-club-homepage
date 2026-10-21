# Optional NixOS module.
#
# Import this from /etc/nixos/configuration.nix if you want Nix to manage
# the development database and nix-ld for prebuilt Python wheels:
#
#   imports = [ /home/george/Projects/movie-club/nix/system.nix ];
#
# The project also works with a project-local Postgres cluster (see the
# Makefile), in which case you do not need to import this module.
{ pkgs, ... }:
{
  programs.nix-ld.enable = true;

  services.postgresql = {
    enable = true;
    package = pkgs.postgresql_16;
    ensureDatabases = [ "movieclub" ];
    ensureUsers = [
      {
        name = "george";
        ensureDBOwnership = true;
      }
    ];
  };
}
