project('mousemap',
  version: '0.3.0',
  meson_version: '>= 1.0',
  license: 'MIT',
  license_files: 'LICENSE',
)

python = import('python').find_installation('python3')
i18n = import('i18n')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
libexecdir = prefix / get_option('libexecdir')
datadir = prefix / get_option('datadir')

# Pacote Python
install_subdir('src/mousemap',
  install_dir: python.get_install_dir(pure: true),
  exclude_directories: ['__pycache__', 'daemon/__pycache__', 'gui/__pycache__'],
)

# Executáveis
foreach exe : [['mousemap', 'mousemap.gui.main'], ['mousemapd', 'mousemap.daemon.main']]
  configure_file(
    input: 'bin/launcher.in',
    output: exe[0],
    configuration: {'PYTHON': python.full_path(), 'MODULE': exe[1]},
    install_dir: bindir,
    install_mode: 'rwxr-xr-x',
  )
endforeach

subdir('data')
subdir('po')

test('unit',
  python,
  args: ['-m', 'unittest', 'discover', '-s', meson.project_source_root() / 'tests',
         '-t', meson.project_source_root()],
  env: {'PYTHONPATH': meson.project_source_root() / 'src'},
)
