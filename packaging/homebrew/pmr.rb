class Pmr < Formula
  include Language::Python::Virtualenv

  desc "Missing CLI and Python library for Adobe Premiere Pro"
  homepage "https://github.com/mhadifilms/pmr"
  # url + sha256 are filled in from the published PyPI sdist at release time:
  #   url "https://files.pythonhosted.org/packages/.../pmr-1.0.0.tar.gz"
  #   sha256 "<sdist sha256>"
  url "PYPI_SDIST_URL"
  sha256 "PYPI_SDIST_SHA256"
  license "MIT"

  depends_on "python@3.12"

  # Resource stanzas below are (re)generated after the sdist is on PyPI:
  #   brew update-python-resources Formula/pmr.rb
  # pmr's runtime deps are rich, typer, pyyaml, websockets (+ their trees).
  # mcp is intentionally omitted here — the CLI/library work without it;
  # `pmr mcp serve` is available via `pip install pmr` (matches dvr's tap).

  # <<RESOURCES>>

  def install
    virtualenv_install_with_resources
  end

  test do
    # --version exits 0 and prints a PEP 440-shaped version string.
    version_output = shell_output("#{bin}/pmr --version")
    assert_match(/\d+\.\d+\.\d+/, version_output)

    # --help exits 0 and lists core commands (no Premiere required).
    help_output = shell_output("#{bin}/pmr --help")
    %w[inspect project timeline render diff snapshot lint schema plugin].each do |cmd|
      assert_match cmd, help_output
    end

    # media scan works fully offline.
    require "fileutils"
    FileUtils.touch "#{testpath}/a.mov"
    scan = shell_output("#{bin}/pmr --format json media scan #{testpath}")
    assert_match "a.mov", scan
  end
end
