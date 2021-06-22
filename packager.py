import os
import glob
import tarfile


# CLOUD_BENCHMARKING_DIR = os.path.join('n://', 'workspace', 'cloud-benchmarking')
CLOUD_BENCHMARKING_ATTEMPT_DIR = os.path.join('n://', 'workspace', 'cloud-benchmarking-run-attempts', 'pkg')

if __name__ == '__main__':
    tarfile_path = os.path.join('terraform', 'deployer-package.tar.gz')
    with tarfile.open(tarfile_path, 'w:gz') as tar:

        # add the non-terraform required files
        # f = os.path.join(CLOUD_BENCHMARKING_ATTEMPT_DIR, 'pyterra.py')
        # tar.add(f, recursive=False, arcname=os.path.basename(f))

        # now add all the terraform stuff, but not all of it (.terraform, state, etc)
        tffiles = glob.glob(os.path.join(CLOUD_BENCHMARKING_ATTEMPT_DIR, '**'), recursive=True)
        for tffile in tffiles:
            if '.terraform' in tffile:
                continue
            if tffile.endswith('.backup') or tffile.endswith('.tfstate'):
                continue
            filename = os.path.join(*(tffile.split(os.path.sep)[2:]))
            tar.add(tffile, recursive=False, arcname=filename)
