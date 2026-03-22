from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'apoptotic_loader'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Craig McClurkin',
    maintainer_email='craig.mcclurkin@louisville.edu',
    description='Apoptotic Model Loading — programmed cell death for robotics AI.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'checkpoint_registry_node = apoptotic_loader.checkpoint_registry_node:main',
            'apoptotic_manager_node = apoptotic_loader.manager_node:main',
            'drift_observer_node = apoptotic_loader.drift_observer_node:main',
            'safe_stop_node = apoptotic_loader.safe_stop_node:main',
        ],
    },
)
