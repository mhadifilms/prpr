class Prpr < Formula
  include Language::Python::Virtualenv

  desc "Missing CLI and Python library for Adobe Premiere Pro"
  homepage "https://github.com/mhadifilms/prpr"
  # url + sha256 are filled in from the published PyPI sdist at release time:
  #   url "https://files.pythonhosted.org/packages/.../prpr-1.0.0.tar.gz"
  #   sha256 "<sdist sha256>"
  url "https://files.pythonhosted.org/packages/00/77/84c388f2c580a2a6e3064911ea02f0a413e2cb4435930040ce40daa2b712/prpr-1.0.0.tar.gz"
  sha256 "6e0918eb0488387465c91dcf770afde72011be54282cb82afa05ce7c5decc15b"
  license "MIT"

  depends_on "libyaml"
  depends_on "python@3.12"

  # Resource stanzas below are (re)generated after the sdist is on PyPI:
  #   brew update-python-resources Formula/prpr.rb
  # prpr's runtime deps are rich, typer, pyyaml, websockets (+ their trees).
  # mcp is intentionally omitted here — the CLI/library work without it;
  # `prpr mcp serve` is available via `pip install prpr` (matches dvr's tap).

  resource "annotated-doc" do
    url "https://files.pythonhosted.org/packages/57/ba/046ceea27344560984e26a590f90bc7f4a75b06701f653222458922b558c/annotated_doc-0.0.4.tar.gz"
    sha256 "fbcda96e87e9c92ad167c2e53839e57503ecfda18804ea28102353485033faa4"
  end
  resource "click" do
    url "https://files.pythonhosted.org/packages/bb/63/f9e1ea081ce35720d8b92acde70daaedace594dc93b693c869e0d5910718/click-8.3.3.tar.gz"
    sha256 "398329ad4837b2ff7cbe1dd166a4c0f8900c3ca3a218de04466f38f6497f18a2"
  end
  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/5b/f5/4ec618ed16cc4f8fb3b701563655a69816155e79e24a17b651541804721d/markdown_it_py-4.0.0.tar.gz"
    sha256 "cb0a2b4aa34f932c007117b194e945bd74e0ec24133ceb5bac59009cda1cb9f3"
  end
  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/d6/54/cfe61301667036ec958cb99bd3efefba235e65cdeb9c84d24a8293ba1d90/mdurl-0.1.2.tar.gz"
    sha256 "bb413d29f5eea38f31dd4754dd7377d4465116fb207585f97bf925588687c1ba"
  end
  resource "Pygments" do
    url "https://files.pythonhosted.org/packages/c3/b2/bc9c9196916376152d655522fdcebac55e66de6603a76a02bca1b6414f6c/pygments-2.20.0.tar.gz"
    sha256 "6757cd03768053ff99f3039c1a36d6c0aa0b263438fcab17520b30a303a82b5f"
  end
  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end
  resource "rich" do
    url "https://files.pythonhosted.org/packages/c0/8f/0722ca900cc807c13a6a0c696dacf35430f72e0ec571c4275d2371fca3e9/rich-15.0.0.tar.gz"
    sha256 "edd07a4824c6b40189fb7ac9bc4c52536e9780fbbfbddf6f1e2502c31b068c36"
  end
  resource "shellingham" do
    url "https://files.pythonhosted.org/packages/58/15/8b3609fd3830ef7b27b655beb4b4e9c62313a4e8da8c676e142cc210d58e/shellingham-1.5.4.tar.gz"
    sha256 "8dbca0739d487e5bd35ab3ca4b36e11c4078f3a234bfce294b0a0291363404de"
  end
  resource "typer" do
    url "https://files.pythonhosted.org/packages/83/b8/9ebb531b6c2d377af08ac6746a5df3425b21853a5d2260876919b58a2a4a/typer-0.24.2.tar.gz"
    sha256 "ec070dcfca1408e85ee203c6365001e818c3b7fffe686fd07ff2d68095ca0480"
  end
  resource "websockets" do
    url "https://files.pythonhosted.org/packages/8c/02/b9a097e1e16fee4e2fd1ec8c39f6a9c5d6257bae8fa12640caf869f54436/websockets-16.1.tar.gz"
    sha256 "299468cbe42e2b9981134c7c51d99387d8a7bf562b00183b3eec53f882846dad"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    # --version exits 0 and prints a PEP 440-shaped version string.
    version_output = shell_output("#{bin}/prpr --version")
    assert_match(/\d+\.\d+\.\d+/, version_output)

    # --help exits 0 and lists core commands (no Premiere required).
    help_output = shell_output("#{bin}/prpr --help")
    %w[inspect project timeline render diff snapshot lint schema plugin].each do |cmd|
      assert_match cmd, help_output
    end

    # media scan works fully offline.
    touch "#{testpath}/a.mov"
    scan = shell_output("#{bin}/prpr --format json media scan #{testpath}")
    assert_match "a.mov", scan
  end
end
