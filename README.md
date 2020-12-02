# fbmeshd

`fbmeshd` is the core technology behind Facebook's Self-organizing Mesh Access
(SoMA) network.

`fbmeshd` uses 802.11s to form links with neighboring nodes in wireless range.
802.11s path selection and forwarding are disabled and `fbmeshd`'s custom `a12s`
protocol is used for routing over such links.

## Device Requirements

Devices must be using a Qualcomm chipset and have support for `ath10k` drivers.

## Getting Started

`fbmeshd` is built using `CMake`. To run an `fbmeshd` mesh, you need to build and
install `fbmeshd` on a wireless device such as an access point.

`fbmeshd` can be easily started using the command in `scripts/`
```
$ run_fbmeshd.sh
```
which will cause it to form L2 links and handle L3 routing.

## Contribute

Take a look at [`CONTRIBUTING.md`](CONTRIBUTING.md) to get started contributing.

## Code of Conduct

The code of conduct is briefly described in [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

## License

`fbmeshd` is MIT licensed.
