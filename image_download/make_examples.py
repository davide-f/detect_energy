from PIL import Image
from osgeo import osr, gdal
import numpy as np
from gdalconst import *
from shapely.geometry import Polygon
import geopandas as gpd
import folium
import os
import rtree
import pygeos
import uuid

# os.chdir(os.path.dirname(os.path.abspath(__file__)))  # move up to parent directory


def make_polygon_list(path, resume_file=None):
    """
    Creates GeoDataFrame, checks the tif files in a desired dir 
    and adds their geometries (with respective file name) as row
    to GeoDataFrame
    
    -----------
    Arguments:
    
    path : (str)
        directory with tif files
        
    resume_file : (str or None)
        if None: initializes net GeoDataFrame
        otherwise loads (and resumes from) existing one
        
    """
    
    tif_files = []
    
    # iterate over all .tif files in desired dir
    for filename in os.listdir(path):
        if filename.endswith(".tif"): 
            tif_files.append(os.path.join(path, filename))
        
    # add data to existing dataframe if desired
    try:
        coverage = gpd.read_file(resume_file)
        print("Adding coverage to f{resume_file}")
    except:
        coverage = gpd.GeoDataFrame({"filename": [], "geometry": []})
        
    # extract geometries of .tif files and add to geodataframe
    for file in tif_files:
        info = gdal.Info(file, format="json")
        corners = info["cornerCoordinates"]
        poly = Polygon((
                    corners["upperLeft"],
                    corners["upperRight"],
                    corners["lowerRight"],
                    corners["lowerLeft"]
                        ))
        coverage = coverage.append({"filename": file, "geometry": poly}, ignore_index=True)

    coverage = coverage.set_crs(epsg=4326)

    return coverage




def make_examples(assets, 
                  coverage, 
                  img_path="/../examples/",
                  max_length=10, 
                  height=512, 
                  width=512):
    """
    Expects dataframe of energy infrastructure assets in fn. Iterates over df
    and for each asset finds the respective polygon from coverage geodataframe.
    Then opens the .tif file that corresponds to the polygon and cuts out the 
    respective pixels. The pixels are turned into a png files and saves.
    Additionally, the respective file name, geometry, bbox, is written into
    a new GeoDataFrame
    ----------
    Arguments: 
    assets : (str or GeoDataFrame)
        path to or GeoDataFrame itself of energy assets
    coverage : (str or GeoDataFrame)
        path to or GeoDataFrame itself of geometries satellite imagery 
    img_path : (str)
        path to directory where resulting examples will vbe stored
    max_length : (int / None)
        restricts number of images created if desired
    height : (int)
        number of pixels in y direction
    width : (int)
        number of pixels in x direction
    ----------
    Returns:
    dataset : (GeoDataFrame)
        df of created examples. contains for each image:
            filename (ending in .png)
            for bbox: upperleft and lowerright
            geometry as Polygon   
    Also
    Saves created examples as .png files to img_path
    In the same directory the GeoJSON of the respective 
    GeoDataFrame dataset is stored in the same directory
    """

    img_path = os.path.abspath("") + img_path
    
    if isinstance(assets, str): assets = gpd.read_file(assets)
    if isinstance(coverage, str): coverage = gpd.read_file(coverage)

    # set up resulting dataset of examples (with towers)
    dataset = gpd.GeoDataFrame({"filename": [], 
                                "ul_x": [], "ul_y": [], "lr_x": [], "lr_y": [], 
                                "geometry": []})

    assets = gpd.sjoin(assets, coverage, how="inner")
    assets = assets.drop(["index_right"], axis=1)
    
    # iterate over .tif files
    for i, image in enumerate(coverage["filename"]):

        # open files
        ds = gdal.Open(image)
        info = gdal.Info(image, format="json")
        bands = [ds.GetRasterBand(i) for i in range(1, 4)]

        # extract relevant geographical data
        transform = info["geoTransform"]
        upper_left = np.array([transform[0], transform[3]])
        pixel_size = np.array([transform[1], transform[5]])

        # iterate over assets in that image
        for idx, row in assets[assets["filename"] == image].iterrows():

            # compute relevant pixels
            p = row.geometry
            coords = np.array([p.xy[0][0], p.xy[1][0]])
            pixels = np.around((coords - upper_left) / pixel_size)
            pixels -= np.array([width // 2, height // 2])

            # add random offset (8 is minimal distance to image boundary)
            offset = np.zeros(2)
            offset[0] = np.random.randint(-width//2 + 8, width//2 - 8)
            offset[1] = np.random.randint(-height//2 + 8, height//2 - 8)
            
            pixels -= offset
            x, y = int(pixels[0]), int(pixels[1])

            # set up image and new filename
            filename = str(int(row.id))
            new_img = np.zeros((height, width, 3), dtype=np.uint8)
            
            # transfer pixel data
            try:
                for i in range(3):
                    new_img[:,:,i] = bands[i].ReadAsArray(x, y, width, height)
            except:
                continue

            # transform array to image
            img = Image.fromarray(new_img, 'RGB')
            img.save(img_path + filename + ".png", quality=100)

            # create Polygon of created image
            img_corner = upper_left + pixels*pixel_size
            img_polygon = Polygon([
                                   img_corner,
                                   img_corner + pixel_size*np.array([width,0]),
                                   img_corner + pixel_size*np.array([width,height]),
                                   img_corner + pixel_size*np.array([0,height])
                                  ])

            # get pixels of bbox; format: (ul_x, ul_y, lr_x, lr_y)
            tower_height = 25
            tower_width = 30
            ul = np.array([width//2, height//2]) + offset
            bbox = [
                    ul[0] - tower_width // 2,
                    ul[1] - tower_height // 2,
                    ul[0] + tower_width // 2,
                    ul[1] + tower_height // 2
            ]

            # add resulting image to dataset
            dataset = dataset.append({"filename": filename,
                                      "ul_x": bbox[0],
                                      "ul_y": bbox[1],
                                      "lr_x": bbox[2],
                                      "lr_y": bbox[3],
                                      "geometry": img_polygon}, 
                                      ignore_index=True)            

            # save results inbetween
            if len(dataset)%50 == 0:
                dataset = dataset.set_crs(epsg=4326)
                dataset.to_file(img_path + "tower_examples.geojson", driver="GeoJSON")

            # early stoppage
            if len(dataset) == max_length:
                dataset.to_file(img_path + "tower_examples.geojson", driver="GeoJSON")
                return

            print("Created {} Examples!".format(len(dataset)))


if __name__ == "__main__":
    # coverage = make_polygon_list(os.path.join(os.getcwd(), "images"))
    coverage = make_polygon_list("./")
    coverage.to_file("sierra_leone_coverage.json", driver="GeoJSON")
    # SL_RAW_TOWERS = os.path.join(os.path.dirname(os.getcwd()), "data", "SL_raw_towers.geojson")
    # make_examples(SL_RAW_TOWERS, coverage, img_path="/examples/", max_length=500)
    make_examples("sierra-leone_raw_towers.geojson", coverage,
                          max_length=500)
