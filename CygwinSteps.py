from buildbot.steps.vstudio import *


def addEnvPath(env, name, value):
    """ concat a path for this name """
    try:
        oldval = env[name]
        if not oldval.endswith(':'):
            oldval = oldval + ':'
    except KeyError:
        oldval = ""
    if not value.endswith(':'):
        value = value + ':'
    env[name] = oldval + value


class VS2013Cygwin(VS2013):
    default_installdir = '/cygdrive/c/Program Files (x86)/Microsoft Visual Studio 12.0'

    def setupEnvironment(self, cmd):
        VisualStudio.setupEnvironment(self, cmd)

        VSInstallDir = self.installdir
        VCInstallDir = self.installdir + '/VC'

        addEnvPath(cmd.args['env'], "PATH", VSInstallDir + '/Common7/IDE')
        if self.arch == "x64":
            addEnvPath(cmd.args['env'], "PATH", VCInstallDir + '/BIN/x86_amd64')
        addEnvPath(cmd.args['env'], "PATH", VCInstallDir + '/BIN')
        addEnvPath(cmd.args['env'], "PATH", VSInstallDir + '/Common7/Tools')
        addEnvPath(cmd.args['env'], "PATH", VSInstallDir + '/Common7/Tools/bin')
        addEnvPath(cmd.args['env'], "PATH", VCInstallDir + '/PlatformSDK/bin')
        addEnvPath(cmd.args['env'], "PATH", VSInstallDir + '/SDK/v2.0/bin')
        addEnvPath(cmd.args['env'], "PATH", VCInstallDir + '/VCPackages')
        addEnvPath(cmd.args['env'], "PATH", r'${PATH}')

        addEnvPath(cmd.args['env'], "INCLUDE", VCInstallDir + '/INCLUDE')
        addEnvPath(cmd.args['env'], "INCLUDE", VCInstallDir + '/ATLMFC/include')
        addEnvPath(cmd.args['env'], "INCLUDE", VCInstallDir + '/PlatformSDK/include')

        archsuffix = ''
        if self.arch == "x64":
            archsuffix = '/amd64'
        addEnvPath(cmd.args['env'], "LIB", VCInstallDir + '/LIB' + archsuffix)
        addEnvPath(cmd.args['env'], "LIB", VCInstallDir + '/ATLMFC/LIB' + archsuffix)
        addEnvPath(cmd.args['env'], "LIB", VCInstallDir + '/PlatformSDK/lib' + archsuffix)
        addEnvPath(cmd.args['env'], "LIB", VSInstallDir + '/SDK/v2.0/lib' + archsuffix)


class MsBuild12Cygwin(MsBuild12):
    VCInstallDir='/cygdrive/c/Program Files (x86)/Microsoft Visual Studio 12.0/VC'
    MSBuildInstallDir='/cygdrive/c/Program Files (x86)/MSBuild/12.0'

    def setupEnvironment(self, cmd):
        ShellCommand.setupEnvironment(self, cmd)
        self.setupInstalldir()
        if cmd.args['env'] is None:
            cmd.args['env'] = {}

        addEnvPath(cmd.args['env'],"PATH",self.VCInstallDir+'/bin')
        addEnvPath(cmd.args['env'],"PATH",self.MSBuildInstallDir+'/Bin')

        addEnvPath(cmd.args['env'],"INCLUDE",self.VCInstallDir+'/include')
        addEnvPath(cmd.args['env'],"LIB",self.VCInstallDir+'/lib')

    def start(self):
        if self.platform is None:
            config.error('platform is mandatory. Please specify a string such as "Win32"')

        command = [self.MSBuildInstallDir+"/Bin/MSBuild.exe",
                   self.projectfile,
                   "/p:Configuration=%s" % (self.config),
                   "/p:Platform=%s" % (self.platform),
                   "/maxcpucount:1",
                   "/verbosity:minimal"] # q[uiet], m[inimal], n[ormal], d[etailed], diag[nostic]
        if self.project is not None:
            command.append("/t:%s" % (self.project))
        elif self.mode == "build":
            command.append("/t:Build")
        elif self.mode == "clean":
            command.append("/t:Clean")
        elif self.mode == "rebuild":
            command.append("/t:Rebuild")

        self.setCommand(command)

        return VisualStudio.start(self)


class MsBuild14Cygwin(MsBuild12Cygwin):
    VCInstallDir='/cygdrive/c/Program Files (x86)/Microsoft Visual Studio 14.0/VC'
    MSBuildInstallDir='/cygdrive/c/Program Files (x86)/MSBuild/14.0'
