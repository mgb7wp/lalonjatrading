/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `standalone` empaqueta el servidor con solo las dependencias que usa, en
  // lugar de arrastrar todo node_modules. La imagen baja de ~1 GB a ~200 MB, y
  // en un VPS pequeno eso es la diferencia entre caber y no caber.
  output: "standalone",
};

export default nextConfig;
