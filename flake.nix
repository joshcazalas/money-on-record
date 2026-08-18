{
  description = "Money on Record development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              actionlint
              awscli2
              direnv
              git
              jq
              python314
              shellcheck
              syft
              terraform
              tflint
              uv
            ];

            shellHook = ''
              export AWS_PAGER=""
              export UV_PYTHON="${pkgs.python314}/bin/python"
              export UV_PYTHON_DOWNLOADS=never
            '';
          };
        });

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);
    };
}
