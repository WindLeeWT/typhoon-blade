# Copyright (c) 2017 Tencent Inc.
# All rights reserved.
#
# Author: Li Wenting <wentingli@tencent.com>
# Date:   October 27, 2017

"""

This module defines various toolchain functions for building
targets from sources and custom parameters.
The toolchain function is defined as follows:

    def toolchain_function_name(targets, sources, **kwargs):
        pass

    Return None on success, otherwise a non-zero value to
    indicate failure.

    Parameters:

        * targets: a list of files separated by comma
                   to be built by tool chain
        * sources: a list of files as separated by comma
                   inputs to tool chain
        * kwargs: name=value pairs as parameters for tool chain

"""

import os
import sys
import subprocess
import shutil
import socket
import time
import zipfile
import tarfile

import blade_util
import console
import fatjar


def generate_scm_entry(args):
    scm, revision, url, profile, compiler = args
    f = open(scm, 'w')
    f.write('''
/* This file was generated by blade */
extern "C" {
namespace binary_version {
  extern const int kSvnInfoCount = 1;
  extern const char* const kSvnInfo[] = {"%s\\n"};
  extern const char kBuildType[] = "%s";
  extern const char kBuildTime[] = "%s";
  extern const char kBuilderName[] = "%s";
  extern const char kHostName[] = "%s";
  extern const char kCompiler[] = "%s";
}}

''' % ('%s@%s' % (url, revision),
       profile,
       time.asctime(),
       os.getenv('USER'),
       socket.gethostname(),
       compiler))
    f.close()


_PACKAGE_MANIFEST = 'MANIFEST.TXT'


def archive_package_sources(package, sources, destinations):
    manifest = []
    for i, s in enumerate(sources):
        package(s, destinations[i])
        manifest.append('%s %s' % (blade_util.md5sum_file(s), destinations[i]))
    return manifest


def generate_zip_package(path, sources, destinations):
    zip = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    manifest = archive_package_sources(zip.write, sources, destinations)
    zip.writestr(_PACKAGE_MANIFEST, '\n'.join(manifest) + '\n')
    zip.close()


_TAR_WRITE_MODES = {
    'tar' : 'w',
    'tar.gz' : 'w:gz',
    'tgz' : 'w:gz',
    'tar.bz2' : 'w:bz2',
    'tbz' : 'w:bz2',
}


def generate_tar_package(path, sources, destinations, suffix):
    mode = _TAR_WRITE_MODES[suffix]
    tar = tarfile.open(path, mode, dereference=True)
    manifest = archive_package_sources(tar.add, sources, destinations)
    manifest_path = '%s.MANIFEST' % path
    m = open(manifest_path, 'w')
    m.write('\n'.join(manifest) + '\n\n')
    m.close()
    tar.add(manifest_path, _PACKAGE_MANIFEST)
    tar.close()


def generate_package_entry(args):
    path = args[0]
    manifest = args[1:]
    assert len(manifest) % 2 == 0
    middle = len(manifest) / 2
    sources = manifest[:middle]
    destinations = manifest[middle:]
    if path.endswith('.zip'):
        generate_zip_package(path, sources, destinations)
    else:
        for suffix in _TAR_WRITE_MODES.keys():
            if path.endswith(suffix):
                break
        generate_tar_package(path, sources, destinations, suffix)


def generate_securecc_object_entry(args):
    obj, phony_obj = args
    if not os.path.exists(obj):
        shutil.copy(phony_obj, obj)
    else:
        digest = blade_util.md5sum_file(obj)
        phony_digest = blade_util.md5sum_file(phony_obj)
        if digest != phony_digest:
            shutil.copy(phony_obj, obj)


def generate_resource_index(targets, sources, name, path):
    header, source = targets
    h, c = open(header, 'w'), open(source, 'w')
    full_name = blade_util.regular_variable_name(os.path.join(path, name))
    guard_name = 'BLADE_RESOURCE_%s_H_' % full_name.upper()
    index_name = 'RESOURCE_INDEX_%s' % full_name
    print >>h, '''// This file was automatically generated by blade
#ifndef {0}
#define {0}

#ifdef __cplusplus
extern "C" {{
#endif

#ifndef BLADE_RESOURCE_TYPE_DEFINED
#define BLADE_RESOURCE_TYPE_DEFINED
struct BladeResourceEntry {{
    const char* name;
    const char* data;
    unsigned int size;
}};
#endif
'''.format(guard_name)
    print >>c, '''// This file was automatically generated by blade
#include "{0}"

const struct BladeResourceEntry {1}[] = {{'''.format(header, index_name)

    for s in sources:
        entry_var = blade_util.regular_variable_name(s)
        entry_name = os.path.relpath(s, path)
        entry_size = os.path.getsize(s)
        print >>h, '// %s' % entry_name
        print >>h, 'extern const char RESOURCE_%s[%d];' % (entry_var, entry_size)
        print >>h, 'extern const unsigned RESOURCE_%s_len;\n' % entry_var
        print >>c, '    { "%s", RESOURCE_%s, %s },' % (entry_name, entry_var, entry_size)

    print >>c, '''}};
const unsigned {0}_len = {1};'''.format(index_name, len(sources))
    print >>h, '''// Resource index
extern const struct BladeResourceEntry {0}[];
extern const unsigned {0}_len;

#ifdef __cplusplus
}}  // extern "C"
#endif

#endif  // {1}'''.format(index_name, guard_name)
    h.close()
    c.close()


def generate_resource_index_entry(args):
    name, path = args[0], args[1]
    targets = args[2], args[3]
    sources = args[4:]
    return generate_resource_index(targets, sources, name, path)


def generate_java_jar_entry(args):
    jar, target = args[0], args[1]
    resources_dir = target.replace('.jar', '.resources')
    arg = args[2]
    if arg.endswith('__classes__.jar'):
        classes_jar = arg
        resources = args[3:]
    else:
        classes_jar = ''
        resources = args[2:]

    def archive_resources(resources_dir, resources, new=True):
        if new:
            option = 'cf'
        else:
            option = 'uf'
        cmd = ['%s %s %s' % (jar, option, target)]
        for resource in resources:
            cmd.append("-C '%s' '%s'" % (resources_dir, 
                                         os.path.relpath(resource, resources_dir)))
        return blade_util.shell(cmd)

    if classes_jar:
        shutil.copy2(classes_jar, target)
        if resources:
            return archive_resources(resources_dir, resources, False)
    else:
        return archive_resources(resources_dir, resources, True)


def generate_java_resource_entry(args):
    assert len(args) % 2 == 0
    middle = len(args) / 2
    targets = args[:middle]
    sources = args[middle:]
    for i in range(middle):
        shutil.copy(sources[i], targets[i])


def _get_all_test_class_names_in_jar(jar):
    """Returns a list of test class names in the jar file. """
    test_class_names = []
    zip_file = zipfile.ZipFile(jar, 'r')
    name_list = zip_file.namelist()
    for name in name_list:
        basename = os.path.basename(name)
        # Exclude inner class and Test.class
        if (basename.endswith('Test.class') and
            len(basename) > len('Test.class') and
            not '$' in basename):
            class_name = name.replace('/', '.')[:-6] # Remove .class suffix
            test_class_names.append(class_name)
    zip_file.close()
    return test_class_names


def _generate_java_test_coverage_flag(targetundertestpkg):
    jacoco_agent = os.environ.get('JACOCOAGENT')
    if targetundertestpkg and jacoco_agent:
        jacoco_agent = os.path.abspath(jacoco_agent)
        packages = targetundertestpkg.split(':')
        options = [
            'includes=%s' % ':'.join([p + '.*' for p in packages if p]),
            'output=file',
        ]
        return '-javaagent:%s=%s' % (jacoco_agent, ','.join(options))
    return ''


def _generate_java_test(script, main_class, jars, args, targetundertestpkg):
    f = open(script, 'w')
    f.write(
"""#!/bin/sh
# Auto generated wrapper shell script by blade

if [ -n "$BLADE_COVERAGE" ]
then
  coverage_options="%s"
fi

exec java $coverage_options -classpath %s %s %s $@
""" % (_generate_java_test_coverage_flag(targetundertestpkg), ':'.join(jars), main_class, args))
    f.close()
    os.chmod(script, 0755)


def generate_java_test_entry(args):
    main_class, targetundertestpkg, script, jar = args[:4]
    if targetundertestpkg == '__targetundertestpkg__':
        targetundertestpkg = ''
    jars = args[3:]
    test_class_names = _get_all_test_class_names_in_jar(jar)
    return _generate_java_test(script, main_class, jars, ' '.join(test_class_names),
                               targetundertestpkg)


def generate_fat_jar_entry(args):
    jar = args[0]
    console.set_log_file('%s.log' % jar.replace('.fat.jar', '__fatjar__'))
    console.color_enabled = True
    fatjar.console_logging = True
    fatjar.generate_fat_jar(jar, args[1:])


def generate_one_jar(onejar,
                     main_class,
                     main_jar,
                     jars,
                     bootjar):
    path = onejar
    onejar = zipfile.ZipFile(path, 'w')
    jar_path_set = set()
    # Copy files from one-jar-boot.jar to the target jar
    zip_file = zipfile.ZipFile(bootjar, 'r')
    name_list = zip_file.namelist()
    for name in name_list:
        if not name.lower().endswith('manifest.mf'): # Exclude manifest
            onejar.writestr(name, zip_file.read(name))
            jar_path_set.add(name)
    zip_file.close()

    # Main jar and dependencies
    onejar.write(main_jar, os.path.join('main',
                                        os.path.basename(main_jar)))
    for dep in jars:
        dep_name = os.path.basename(dep)
        onejar.write(dep, os.path.join('lib', dep_name))

    # Copy resources to the root of target onejar
    for jar in [main_jar] + jars:
        jar = zipfile.ZipFile(jar, 'r')
        jar_name_list = jar.namelist()
        for name in jar_name_list:
            if name.endswith('.class') or name.upper().startswith('META-INF'):
                continue
            if name not in jar_path_set:
                jar_path_set.add(name)
                onejar.writestr(name, jar.read(name))
        jar.close()

    # Manifest
    # Note that the manifest file must end with a new line or carriage return
    onejar.writestr(os.path.join('META-INF', 'MANIFEST.MF'),
                                 '''Manifest-Version: 1.0
Main-Class: com.simontuffs.onejar.Boot
One-Jar-Main-Class: %s

''' % main_class)
    onejar.close()


def generate_one_jar_entry(args):
    bootjar, main_class, onejar, main_jar = args[:4]
    jars = args[4:]
    generate_one_jar(onejar, main_class, main_jar, jars, bootjar)


def generate_java_binary_entry(args):
    script, onejar = args
    basename = os.path.basename(onejar)
    fullpath = os.path.abspath(onejar)
    f = open(script, 'w')
    f.write(
"""#!/bin/sh
# Auto generated wrapper shell script by blade

jar=`dirname "$0"`/"%s"
if [ ! -f "$jar" ]; then
  jar="%s"
fi

exec java -jar "$jar" $@
""" % (basename, fullpath))
    f.close()
    os.chmod(script, 0755)


def generate_scala_test_entry(args):
    java, scala, script, jar = args[:4]
    jars = args[3:]
    test_class_names = _get_all_test_class_names_in_jar(jar)
    scala, java = os.path.abspath(scala), os.path.abspath(java)
    run_args = 'org.scalatest.run ' + ' '.join(test_class_names)
    f = open(script, 'w')
    f.write(
"""#!/bin/sh
# Auto generated wrapper shell script by blade

JAVACMD=%s exec %s -classpath %s %s $@

""" % (java, scala, ':'.join(jars), run_args))
    f.close()
    os.chmod(script, 0755)


def generate_shell_test_entry(args):
    wrapper = args[0]
    scripts = args[1:]
    f = open(wrapper, 'w')
    f.write(
"""#!/bin/sh
# Auto generated wrapper shell script by blade

set -e

%s

""" % '\n'.join(['. %s' % os.path.abspath(s) for s in scripts])
)
    f.close()
    os.chmod(wrapper, 0755)


def generate_shell_testdata_entry(args):
    path = args[0]
    testdata = args[1:]
    assert len(testdata) % 2 == 0
    middle = len(testdata) / 2
    sources = testdata[:middle]
    destinations = testdata[middle:]
    f = open(path, 'w')
    for i in range(middle):
        f.write('%s %s\n' % (os.path.abspath(sources[i]), destinations[i]))
    f.close()


def generate_python_library_entry(args):
    basedir, pylib = args[0], args[1]
    if basedir == '__pythonbasedir__':
        basedir = ''
    sources = []
    for py in args[2:]:
        digest = blade_util.md5sum_file(py)
        sources.append((py, digest))
    f = open(pylib, 'w')
    f.write(str({
        'base_dir' : basedir,
        'srcs' : sources
    }))
    f.close()


def _update_init_py_dirs(arcname, dirs, dirs_with_init_py):
    dir = os.path.dirname(arcname)
    if os.path.basename(arcname) == '__init__.py':
        dirs_with_init_py.add(dir)
    while dir:
        dirs.add(dir)
        dir = os.path.dirname(dir)


def generate_python_binary_entry(args):
    basedir, mainentry, path = args[:3]
    if basedir == '__pythonbasedir__':
        basedir = ''
    pybin = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)
    dirs, dirs_with_init_py = set(), set()
    for arg in args[3:]:
        pylib = open(arg)
        data = eval(pylib.read())
        pylib.close()
        pylib_base_dir = data['base_dir']
        for libsrc, digest in data['srcs']:
            arcname = os.path.relpath(libsrc, pylib_base_dir)
            _update_init_py_dirs(arcname, dirs, dirs_with_init_py)
            pybin.write(libsrc, arcname)

    # Insert __init__.py into each dir if missing
    dirs_missing_init_py = dirs - dirs_with_init_py
    for dir in sorted(dirs_missing_init_py):
        pybin.writestr(os.path.join(dir, '__init__.py'), '')
    pybin.writestr('__init__.py', '')
    pybin.close()

    f = open(path, 'rb')
    zip_content = f.read()
    f.close()
    # Insert bootstrap before zip, it is also a valid zip file.
    # unzip will seek actually start until meet the zip magic number.
    bootstrap = ('#!/bin/sh\n\n'
                 'PYTHONPATH="$0:$PYTHONPATH" exec python -m "%s" "$@"\n') % mainentry
    f = open(path, 'wb')
    f.write(bootstrap)
    f.write(zip_content)
    f.close()
    os.chmod(path, 0755)


toolchains = {
    'scm' : generate_scm_entry,
    'package' : generate_package_entry,
    'securecc_object' : generate_securecc_object_entry,
    'resource_index' : generate_resource_index_entry,
    'java_jar' : generate_java_jar_entry,
    'java_resource' : generate_java_resource_entry,
    'java_test' : generate_java_test_entry,
    'java_fatjar' : generate_fat_jar_entry,
    'java_onejar' : generate_one_jar_entry,
    'java_binary' : generate_java_binary_entry,
    'scala_test' : generate_scala_test_entry,
    'shell_test' : generate_shell_test_entry,
    'shell_testdata' : generate_shell_testdata_entry,
    'python_library' : generate_python_library_entry,
    'python_binary' : generate_python_binary_entry,
}


if __name__ == '__main__':
    name = sys.argv[1]
    ret = toolchains[name](sys.argv[2:])
    if ret:
        sys.exit(ret)

