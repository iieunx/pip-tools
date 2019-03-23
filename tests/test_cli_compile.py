import os
from textwrap import dedent
import subprocess
import sys
import mock

from click.testing import CliRunner

import pytest

from piptools._compat.pip_compat import path_to_url
from piptools.repositories import PyPIRepository
from piptools.scripts.compile import cli
from pip._vendor.packaging.version import parse as parse_version
from pip import __version__ as pip_version
from .utils import invoke


PIP_VERSION = parse_version(os.environ.get('PIP', pip_version))

fail_below_pip9 = pytest.mark.xfail(
    PIP_VERSION < parse_version('9'),
    reason="needs pip 9 or greater"
)


@pytest.fixture
def pip_conf(tmpdir, monkeypatch):
    test_conf = dedent("""\
        [global]
        index-url = http://example.com
        trusted-host = example.com
    """)

    pip_conf_file = 'pip.conf' if os.name != 'nt' else 'pip.ini'
    path = (tmpdir / pip_conf_file).strpath

    with open(path, 'w') as f:
        f.write(test_conf)

    monkeypatch.setenv('PIP_CONFIG_FILE', path)

    try:
        yield path
    finally:
        os.remove(path)


@pytest.mark.usefixtures('pip_conf')
def test_default_pip_conf_read(runner):
    # preconditions
    with open('requirements.in', 'w'):
        pass
    out = runner.invoke(cli, ['-v'])

    # check that we have our index-url as specified in pip.conf
    assert 'Using indexes:\n  http://example.com' in out.output
    assert '--index-url http://example.com' in out.output


@pytest.mark.usefixtures('pip_conf')
def test_command_line_overrides_pip_conf(runner):
    # preconditions
    with open('requirements.in', 'w'):
        pass
    out = runner.invoke(cli, ['-v', '-i', 'http://override.com'])

    # check that we have our index-url as specified in pip.conf
    assert 'Using indexes:\n  http://override.com' in out.output


@pytest.mark.usefixtures('pip_conf')
def test_command_line_setuptools_read(runner):
    package = open('setup.py', 'w')
    package.write(dedent("""\
        from setuptools import setup
        setup(install_requires=[])
    """))
    package.close()
    out = runner.invoke(cli)

    # check that pip-compile generated a configuration
    assert 'This file is autogenerated by pip-compile' in out.output
    assert os.path.exists('requirements.txt')


@pytest.mark.usefixtures('pip_conf')
@pytest.mark.parametrize('options, expected_output_file', [
    # For the `pip-compile` output file should be "requirements.txt"
    ([], 'requirements.txt'),
    # For the `pip-compile --output-file=output.txt` output file should be "output.txt"
    (['--output-file', 'output.txt'], 'output.txt'),
    # For the `pip-compile setup.py` output file should be "requirements.txt"
    (['setup.py'], 'requirements.txt'),
    # For the `pip-compile setup.py --output-file=output.txt` output file should be "output.txt"
    (['setup.py', '--output-file', 'output.txt'], 'output.txt'),
])
def test_command_line_setuptools_output_file(options, expected_output_file):
    """
    Test the output files for setup.py as a requirement file.
    """
    runner = CliRunner()
    with runner.isolated_filesystem():
        package = open('setup.py', 'w')
        package.write(dedent("""\
            from setuptools import setup
            setup(install_requires=[])
        """))
        package.close()

        out = runner.invoke(cli, options)
        assert out.exit_code == 0
        assert os.path.exists(expected_output_file)


@pytest.mark.usefixtures('pip_conf')
def test_find_links_option(runner):
    with open('requirements.in', 'w'):
        pass
    out = runner.invoke(cli, ['-v', '-f', './libs1', '-f', './libs2'])

    # Check that find-links has been passed to pip
    assert 'Configuration:\n  -f ./libs1\n  -f ./libs2' in out.output


@pytest.mark.usefixtures('pip_conf')
def test_extra_index_option(runner):
    with open('requirements.in', 'w'):
        pass
    out = runner.invoke(cli, ['-v',
                              '--extra-index-url', 'http://extraindex1.com',
                              '--extra-index-url', 'http://extraindex2.com'])
    assert ('Using indexes:\n'
            '  http://example.com\n'
            '  http://extraindex1.com\n'
            '  http://extraindex2.com' in out.output)
    assert ('--index-url http://example.com\n'
            '--extra-index-url http://extraindex1.com\n'
            '--extra-index-url http://extraindex2.com' in out.output)


@pytest.mark.usefixtures('pip_conf')
def test_trusted_host(runner):
    with open('requirements.in', 'w'):
        pass
    out = runner.invoke(cli, ['-v',
                              '--trusted-host', 'example.com',
                              '--trusted-host', 'example2.com'])
    assert ('--trusted-host example.com\n'
            '--trusted-host example2.com\n' in out.output)


@pytest.mark.usefixtures('pip_conf')
def test_trusted_host_no_emit(runner):
    with open('requirements.in', 'w'):
        pass
    out = runner.invoke(cli, ['-v',
                              '--trusted-host', 'example.com',
                              '--no-emit-trusted-host'])
    assert '--trusted-host example.com' not in out.output


def test_realistic_complex_sub_dependencies(runner):
    wheels_dir = 'wheels'

    # make a temporary wheel of a fake package
    subprocess.check_output(['pip', 'wheel',
                             '--no-deps',
                             '-w', wheels_dir,
                             os.path.join(os.path.split(__file__)[0], 'test_data', 'fake_package', '.')])

    with open('requirements.in', 'w') as req_in:
        req_in.write('fake_with_deps')  # require fake package

    out = runner.invoke(cli, ['-v',
                              '-n', '--rebuild',
                              '-f', wheels_dir])

    assert out.exit_code == 0


def test_run_as_module_compile():
    """piptools can be run as ``python -m piptools ...``."""

    status, output = invoke([
        sys.executable, '-m', 'piptools', 'compile', '--help',
    ])

    # Should have run pip-compile successfully.
    output = output.decode('utf-8')
    assert output.startswith('Usage:')
    assert 'Compiles requirements.txt from requirements.in' in output
    assert status == 0


def test_editable_package(runner):
    """ piptools can compile an editable """
    fake_package_dir = os.path.join(os.path.split(__file__)[0], 'test_data', 'small_fake_package')
    fake_package_dir = path_to_url(fake_package_dir)
    with open('requirements.in', 'w') as req_in:
        req_in.write('-e ' + fake_package_dir)  # require editable fake package

    out = runner.invoke(cli, ['-n'])

    assert out.exit_code == 0
    assert fake_package_dir in out.output
    assert 'six==1.10.0' in out.output


def test_editable_package_vcs(runner):
    vcs_package = (
        'git+git://github.com/pytest-dev/pytest-django'
        '@21492afc88a19d4ca01cd0ac392a5325b14f95c7'
        '#egg=pytest-django'
    )
    with open('requirements.in', 'w') as req_in:
        req_in.write('-e ' + vcs_package)
    out = runner.invoke(cli, ['-n',
                              '--rebuild'])
    print(out.output)
    assert out.exit_code == 0
    assert vcs_package in out.output
    assert 'pytest' in out.output  # dependency of pytest-django


def test_locally_available_editable_package_is_not_archived_in_cache_dir(tmpdir, runner):
    """ piptools will not create an archive for a locally available editable requirement """
    cache_dir = tmpdir.mkdir('cache_dir')

    fake_package_dir = os.path.join(os.path.split(__file__)[0], 'test_data', 'small_fake_package')
    fake_package_dir = path_to_url(fake_package_dir)

    with mock.patch('piptools.repositories.pypi.CACHE_DIR', new=str(cache_dir)):
        with open('requirements.in', 'w') as req_in:
            req_in.write('-e ' + fake_package_dir)  # require editable fake package

        out = runner.invoke(cli, ['-n'])

        assert out.exit_code == 0
        assert fake_package_dir in out.output
        assert 'six==1.10.0' in out.output

    # we should not find any archived file in {cache_dir}/pkgs
    assert not os.listdir(os.path.join(str(cache_dir), 'pkgs'))


def test_input_file_without_extension(runner):
    """
    piptools can compile a file without an extension,
    and add .txt as the defaut output file extension.
    """
    with open('requirements', 'w') as req_in:
        req_in.write('six==1.10.0')

    out = runner.invoke(cli, ['requirements'])

    assert out.exit_code == 0
    assert 'six==1.10.0' in out.output
    assert os.path.exists('requirements.txt')


def test_upgrade_packages_option(runner):
    """
    piptools respects --upgrade-package/-P inline list.
    """
    fake_package_dir = os.path.join(os.path.split(__file__)[0], 'test_data', 'minimal_wheels')
    with open('requirements.in', 'w') as req_in:
        req_in.write('small-fake-a\nsmall-fake-b')
    with open('requirements.txt', 'w') as req_in:
        req_in.write('small-fake-a==0.1\nsmall-fake-b==0.1')

    out = runner.invoke(cli, [
        '-P', 'small-fake-b',
        '-f', fake_package_dir,
    ])

    assert out.exit_code == 0
    assert 'small-fake-a==0.1' in out.output
    assert 'small-fake-b==0.3' in out.output


def test_upgrade_packages_version_option(runner):
    """
    piptools respects --upgrade-package/-P inline list with specified versions.
    """
    fake_package_dir = os.path.join(os.path.split(__file__)[0], 'test_data', 'minimal_wheels')
    with open('requirements.in', 'w') as req_in:
        req_in.write('small-fake-a\nsmall-fake-b')
    with open('requirements.txt', 'w') as req_in:
        req_in.write('small-fake-a==0.1\nsmall-fake-b==0.1')

    out = runner.invoke(cli, [
        '-P', 'small-fake-b==0.2',
        '-f', fake_package_dir,
    ])

    assert out.exit_code == 0
    assert 'small-fake-a==0.1' in out.output
    assert 'small-fake-b==0.2' in out.output


def test_quiet_option(runner):
    with open('requirements', 'w'):
        pass
    out = runner.invoke(cli, ['--quiet', '-n', 'requirements'])
    # Pinned requirements result has not been written to output
    assert 'Dry-run, so nothing updated.' == out.output.strip()


def test_generate_hashes_with_editable(runner):
    small_fake_package_dir = os.path.join(
        os.path.split(__file__)[0], 'test_data', 'small_fake_package')
    small_fake_package_url = path_to_url(small_fake_package_dir)
    with open('requirements.in', 'w') as fp:
        fp.write('-e {}\n'.format(small_fake_package_url))
        fp.write('pytz==2017.2\n')
    out = runner.invoke(
        cli, [
            '--generate-hashes',
            '--index-url', PyPIRepository.DEFAULT_INDEX_URL,
        ],
    )
    expected = (
        '-e {}\n'
        'pytz==2017.2 \\\n'
        '    --hash=sha256:d1d6729c85acea5423671382868627129432fba9a89ecbb248d8d1c7a9f01c67 \\\n'
        '    --hash=sha256:f5c056e8f62d45ba8215e5cb8f50dfccb198b4b9fbea8500674f3443e4689589\n'
    ).format(small_fake_package_url)
    assert out.exit_code == 0
    assert expected in out.output


@fail_below_pip9
def test_filter_pip_markers(runner):
    """
    Check that pip-compile works with pip environment markers (PEP496)
    """
    with open('requirements', 'w') as req_in:
        req_in.write(
            "six==1.10.0\n"
            "unknown_package==0.1; python_version == '1'")

    out = runner.invoke(cli, ['-n', 'requirements'])

    assert out.exit_code == 0
    assert 'six==1.10.0' in out.output
    assert 'unknown_package' not in out.output


def test_no_candidates(runner):
    with open('requirements', 'w') as req_in:
        req_in.write('six>1.0b0,<1.0b0')

    out = runner.invoke(cli, ['-n', 'requirements'])

    assert out.exit_code == 2
    assert 'Skipped pre-versions:' in out.output


def test_no_candidates_pre(runner):
    with open('requirements', 'w') as req_in:
        req_in.write('six>1.0b0,<1.0b0')

    out = runner.invoke(cli, ['-n', 'requirements', '--pre'])

    assert out.exit_code == 2
    assert 'Tried pre-versions:' in out.output


@pytest.mark.usefixtures('pip_conf')
def test_default_index_url():
    status, output = invoke([sys.executable, '-m', 'piptools', 'compile', '--help'])
    output = output.decode('utf-8')

    # Click's subprocess output has \r\r\n line endings on win py27. Fix it.
    output = output.replace('\r\r', '\r')

    assert status == 0
    expected = (
        '  -i, --index-url TEXT            Change index URL (defaults to' + os.linesep +
        '                                  http://example.com)' + os.linesep
    )
    assert expected in output


def test_stdin_without_output_file(runner):
    """
    The --output-file option is required for STDIN.
    """
    out = runner.invoke(cli, ['-n', '-'])

    assert out.exit_code == 2
    assert '--output-file is required if input is from stdin' in out.output


def test_not_specified_input_file(runner):
    """
    It should raise an error if there are no input files or default input files
    such as "setup.py" or "requirements.in".
    """
    out = runner.invoke(cli)
    assert 'If you do not specify an input file' in out.output
    assert out.exit_code == 2


def test_stdin(runner):
    """
    Test compile requirements from STDIN.
    """
    out = runner.invoke(
        cli,
        ['-', '--output-file', 'requirements.txt', '-n'],
        input='six==1.10.0'
    )

    assert 'six==1.10.0' in out.output


def test_multiple_input_files_without_output_file(runner):
    """
    The --output-file option is required for multiple requirement input files.
    """
    with open('src_file1.in', 'w') as req_in:
        req_in.write('six==1.10.0')

    with open('src_file2.in', 'w') as req_in:
        req_in.write('django==2.1')

    out = runner.invoke(cli, ['src_file1.in', 'src_file2.in'])

    assert '--output-file is required if two or more input files are given' in out.output
    assert out.exit_code == 2


def test_mutually_exclusive_upgrade_options(runner):
    """
    The options --upgrade and --upgrade-package should be mutual exclusive.
    """
    with open('requirements.in', 'w') as req_in:
        req_in.write('six==1.10.0')

    out = runner.invoke(cli, ['--upgrade', '--upgrade-package', 'six'])

    assert 'Only one of --upgrade or --upgrade-package can be provided as an argument' in out.output
    assert out.exit_code == 2


@pytest.mark.usefixtures('pip_conf')
@pytest.mark.parametrize('option, expected', [
    ('--annotate', 'six==1.10.0               # via small-fake-with-deps\n'),
    ('--no-annotate', 'six==1.10.0\n'),
])
def test_annotate_option(runner, option, expected):
    """
    The output lines has have annotations if option is turned on.
    """
    fake_package_dir = os.path.join(os.path.split(__file__)[0], 'test_data', 'minimal_wheels')

    with open('requirements.in', 'w') as req_in:
        req_in.write('small_fake_with_deps')

    out = runner.invoke(cli, [option, '-n', '-f', fake_package_dir])

    assert expected in out.output
    assert out.exit_code == 0


@pytest.mark.parametrize('option, attr, expected', [
    ('--cert', 'cert', 'foo.crt'),
    ('--client-cert', 'client_cert', 'bar.pem'),
])
@mock.patch('piptools.scripts.compile.PyPIRepository')
def test_cert_option(MockPyPIRepository, runner, option, attr, expected):
    """
    The options --cert and --client-crt have to be passed to the PyPIRepository.
    """
    with open('requirements.in', 'w') as req_in:
        req_in.write('six==1.10.0')

    out = runner.invoke(cli, [option, expected])

    assert 'six==1.10.0' in out.output

    # Ensure the pip_options in PyPIRepository has have the expected option
    for call in MockPyPIRepository.call_args_list:
        pip_options = call[0][0]
        assert getattr(pip_options, attr) == expected


@pytest.mark.parametrize('option, expected', [
    ('--build-isolation', True),
    ('--no-build-isolation', False),
])
@mock.patch('piptools.scripts.compile.PyPIRepository')
def test_build_isolation_option(MockPyPIRepository, runner, option, expected):
    """
    A value of the --build-isolation/--no-build-isolation flag must be passed to the PyPIRepository.
    """
    with open('requirements.in', 'w'):
        pass

    runner.invoke(cli, [option])

    # Ensure the build_isolation option in PyPIRepository has the expected value.
    assert [call[0][2] for call in MockPyPIRepository.call_args_list] == [expected]
